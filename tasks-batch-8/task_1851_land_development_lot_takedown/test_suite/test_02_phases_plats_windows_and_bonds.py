"""Phase windows and plat pipeline, recordation side effects, and bond math."""
from test_helpers import (
    CLERK,
    DEV,
    ApiErrorId,
    assert_bond,
    assert_lot,
    award_bid,
    create_acquired_parcel,
    create_active_loan,
    create_bond,
    create_funded_draw,
    create_parcel,
    create_phase,
    create_phase_payload,
    create_posted_bond,
    open_contingency,
    submit_plat,
    validate_error,
    validate_paginated,
    validate_success,
    walk_phase_to_recorded,
)


class TestPhaseWindowsAndPlat:
    def test_phase_create_with_inverted_window_rejected(self, api):
        """PRD §3.2: "The window is a half-open interval: it includes its start and excludes its end, so the end must fall strictly after the start or creation fails with `ERR_INVALID_WINDOW`."

        Design: Corner/validations/window_invalid_returns_400
        """
        parcel = create_parcel(parcel_name="WP2")
        resp = api.create_phase(create_phase_payload(
            parcel["id"], phase_name="BAD",
            selling_window_start="2027-03-01T00:00:00Z",
            selling_window_end="2026-09-01T00:00:00Z"), DEV)
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)

    def test_adjacent_selling_windows_accepted(self, api):
        """PRD §3.2: "Pure adjacency is explicitly permitted — a new window starting exactly when a sibling's ends, or ending exactly when a sibling's starts, touches without overlapping."

        Design: Difficulty/resource_temporal_overlap/phase_selling_window_half_open_overlap
        """
        parcel = create_parcel(parcel_name="P15")
        create_phase(parcel["id"], phase_name="A", sequence_number=1,
                     planned_lot_count=10,
                     selling_window_start="2026-09-01T00:00:00Z",
                     selling_window_end="2027-03-01T00:00:00Z")
        adjacent = validate_success(api.create_phase(create_phase_payload(
            parcel["id"], phase_name="B", sequence_number=2, planned_lot_count=10,
            selling_window_start="2027-03-01T00:00:00Z",
            selling_window_end="2027-09-01T00:00:00Z"), DEV), 201)
        assert adjacent["status"] == "PLANNED"

    def test_intersecting_selling_window_rejected(self, api):
        """PRD §3.2: "Windows of sibling phases — every phase of the same parcel, regardless of status — must not overlap: an overlap exists when the new window's start falls before an existing window's end and that existing window's start falls before the new window's end, and any such overlap is rejected with `ERR_PHASE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/phase_selling_window_half_open_overlap
        """
        parcel = create_parcel(parcel_name="P15")
        create_phase(parcel["id"], phase_name="A", sequence_number=1,
                     planned_lot_count=10,
                     selling_window_start="2026-09-01T00:00:00Z",
                     selling_window_end="2027-03-01T00:00:00Z")
        resp = api.create_phase(create_phase_payload(
            parcel["id"], phase_name="C", sequence_number=3, planned_lot_count=10,
            selling_window_start="2027-02-15T00:00:00Z",
            selling_window_end="2027-08-01T00:00:00Z"), DEV)
        validate_error(resp, ApiErrorId.ERR_PHASE_WINDOW_OVERLAP)

    def test_submit_plat_invalid_lot_type_rejected(self, api):
        """PRD §3.2: "Submitting a plat moves a phase from `PLANNED` to `PLAT_SUBMITTED` and records the submission's `plat_lot_count` and `lot_type` — one of `STANDARD`, `PREMIUM`, or `ESTATE` — while `plat_revision` advances from 0 to 1 on this first submission."
        PRD §2.8: "4. **Request shape** — required fields present, types correct, enum values valid, and payload-internal rules such as window ordering and line-item shape; violations yield `ERR_INVALID_REQUEST`, `ERR_INVALID_WINDOW`, or `ERR_INVALID_CONTINGENCY_EXTENSION` (400)."

        Design: Corner/entities/lot_type_invalid_enum_rejected
        """
        parcel = create_parcel(parcel_name="EP")
        phase = create_phase(parcel["id"], planned_lot_count=5)
        resp = api.submit_plat(
            phase["id"], {"plat_lot_count": 5, "lot_type": "MANSION"}, DEV)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_plat_resubmission_increments_revision(self, api):
        """PRD §3.2: "A `decision` of `REJECT` moves it to `PLAT_REJECTED` and requires a present, non-empty `rejection_reason` — a rejection without one is rejected itself with `ERR_INVALID_REQUEST` — and the reason is stored on the phase as `plat_rejection_reason`."
        PRD §3.2: "Rejected plats are resubmitted rather than recreated: submitting again from `PLAT_REJECTED` returns the phase to `PLAT_SUBMITTED`, replaces `plat_lot_count` and `lot_type` with the new submission's values, increments `plat_revision` by one, and clears `plat_rejection_reason` back to null."

        Design: Corner/state_machines/plat_resubmit_increments_revision
        """
        parcel = create_parcel(parcel_name="RP")
        phase = create_phase(parcel["id"], planned_lot_count=5)

        submitted = submit_plat(phase["id"], plat_lot_count=5, lot_type="STANDARD")
        assert submitted["status"] == "PLAT_SUBMITTED"
        assert submitted["plat_revision"] == 1

        rejected = validate_success(api.review_plat(phase["id"], {
            "decision": "REJECT", "rejection_reason": "lot lines misaligned"}, CLERK))
        assert rejected["status"] == "PLAT_REJECTED"
        assert rejected["plat_rejection_reason"] == "lot lines misaligned"

        resubmitted = submit_plat(phase["id"], plat_lot_count=6, lot_type="PREMIUM")
        assert resubmitted["status"] == "PLAT_SUBMITTED"
        assert resubmitted["plat_revision"] == 2
        assert resubmitted["plat_rejection_reason"] is None
        assert resubmitted["plat_lot_count"] == 6
        assert resubmitted["lot_type"] == "PREMIUM"

        approved = validate_success(
            api.review_plat(phase["id"], {"decision": "APPROVE"}, CLERK))
        assert approved["status"] == "PLAT_APPROVED"

    def test_record_plat_generates_exact_lots(self, api):
        """PRD §3.2: "When the clerk records an approved plat, the phase moves from `PLAT_APPROVED` to `PLAT_RECORDED`, `recorded_at` is stamped with the current clock, and the system generates exactly `plat_lot_count` lot rows for the phase: `lot_number` is assigned as the sequence 1 through `plat_lot_count`, each lot's `lot_type` is copied from the recorded plat, and every lot starts with `sales_status` `PLATTED` and `lien_status` `ENCUMBERED`."

        Design: Corner/endpoints/record_plat_generates_exact_lot_count
        """
        parcel = create_parcel(parcel_name="GP2")
        phase = create_phase(parcel["id"], planned_lot_count=3)
        submit_plat(phase["id"], plat_lot_count=3, lot_type="PREMIUM")
        validate_success(api.review_plat(phase["id"], {"decision": "APPROVE"}, CLERK))

        recorded = validate_success(api.record_plat(phase["id"], CLERK))
        assert recorded["status"] == "PLAT_RECORDED"
        assert recorded["recorded_lot_count"] == 3

        lots, meta = validate_paginated(
            api.list_lots(DEV, params={"phase_id": phase["id"]}))
        assert meta["total_count"] == 3
        assert {lot["lot_number"] for lot in lots} == {1, 2, 3}
        for lot in lots:
            assert_lot(lot)
            assert lot["lot_type"] == "PREMIUM"
            assert lot["sales_status"] == "PLATTED"
            assert lot["lien_status"] == "ENCUMBERED"


class TestPhaseActivationGates:
    def test_phase_activate_requires_parcel_acquired(self, api):
        """PRD §3.2: "A `DeveloperOperator` may move a phase from `PLAT_RECORDED` to `ACTIVE` only when two external conditions hold: the owning parcel's status is `ACQUIRED` (otherwise `ERR_PARCEL_NOT_ACQUIRED`), and an infrastructure bond for this exact phase exists in one of `POSTED`, `PARTIALLY_REDUCED`, or `WORK_ACCEPTED` status (otherwise `ERR_BOND_NOT_POSTED_FOR_PHASE`)."

        Design: Corner/state_machines/phase_activate_guard_parcel_not_acquired
        """
        parcel = create_parcel(parcel_name="GP")
        open_contingency(parcel["id"])  # parcel stays CONTINGENCY_ACTIVE
        phase = create_phase(parcel["id"], planned_lot_count=2)
        walk_phase_to_recorded(phase["id"], 2)
        create_posted_bond(phase["id"])
        resp = api.activate_phase(phase["id"], DEV)
        validate_error(resp, ApiErrorId.ERR_PARCEL_NOT_ACQUIRED)

    def test_phase_activate_rejected_until_bond_posted(self, api):
        """PRD §3.2: "A `DeveloperOperator` may move a phase from `PLAT_RECORDED` to `ACTIVE` only when two external conditions hold: the owning parcel's status is `ACQUIRED` (otherwise `ERR_PARCEL_NOT_ACQUIRED`), and an infrastructure bond for this exact phase exists in one of `POSTED`, `PARTIALLY_REDUCED`, or `WORK_ACCEPTED` status (otherwise `ERR_BOND_NOT_POSTED_FOR_PHASE`)."

        Design: Difficulty/cross_entity_state_dependency/phase_activate_requires_bond_posted
        """
        parcel = create_acquired_parcel(parcel_name="P14")
        phase = create_phase(parcel["id"], planned_lot_count=2)
        walk_phase_to_recorded(phase["id"], 2)
        bond = create_bond(phase["id"])
        award_bid(bond["id"], 9000000)  # BID_FINAL: awarded, not posted
        validate_error(api.activate_phase(phase["id"], DEV),
                       ApiErrorId.ERR_BOND_NOT_POSTED_FOR_PHASE)

    def test_phase_activate_succeeds_after_bond_posted(self, api):
        """PRD §3.2: "A `DeveloperOperator` may move a phase from `PLAT_RECORDED` to `ACTIVE` only when two external conditions hold: the owning parcel's status is `ACQUIRED` (otherwise `ERR_PARCEL_NOT_ACQUIRED`), and an infrastructure bond for this exact phase exists in one of `POSTED`, `PARTIALLY_REDUCED`, or `WORK_ACCEPTED` status (otherwise `ERR_BOND_NOT_POSTED_FOR_PHASE`)."
        PRD §3.3: "Posting then moves the bond from `BID_FINAL` to `POSTED`: the supplied `posted_amount_cents` must be at least the current `required_bond_cents` — the boundary is inclusive, an exactly-equal posting succeeds — and anything less is rejected with `ERR_INSUFFICIENT_BOND_POSTED`; the posted amount is stored on `posted_bond_cents`."

        Design: Difficulty/cross_entity_state_dependency/phase_activate_requires_bond_posted
        """
        parcel = create_acquired_parcel(parcel_name="P14")
        phase = create_phase(parcel["id"], planned_lot_count=2)
        walk_phase_to_recorded(phase["id"], 2)
        bond = create_bond(phase["id"])
        award_bid(bond["id"], 9000000)
        validate_success(api.post_bond(
            bond["id"], {"posted_amount_cents": 9900000}, DEV))
        activated = validate_success(api.activate_phase(phase["id"], DEV))
        assert activated["status"] == "ACTIVE"


class TestBondRequirementVariants:
    def test_bond_required_on_provisional_basis_at_create(self, api):
        """PRD §3.3: "The bond starts `ESTIMATED`, and its `required_bond_cents` is computed provisionally as the engineer's estimate increased by ten percent — the estimate multiplied by 11000 basis points over ten thousand — rounded half-up to whole cents."

        Design: Difficulty/dual_variant_calc/bond_requirement_provisional_vs_final
        """
        parcel = create_parcel(parcel_name="P1")
        phase = create_phase(parcel["id"], planned_lot_count=10)
        bond = validate_success(api.create_bond(
            {"phase_id": phase["id"], "engineer_estimate_cents": 10000000}, DEV), 201)
        assert_bond(bond)
        assert bond["status"] == "ESTIMATED"
        # 110% of the 10000000 estimate, provisional basis
        assert bond["required_bond_cents"] == 11000000
        assert bond["posted_bond_cents"] == 0
        assert bond["work_accepted"] is False

    def test_bond_required_switches_to_final_basis_at_award(self, api):
        """PRD §3.3: "When bids come back, awarding the bid moves the bond from `ESTIMATED` to `BID_FINAL`: the supplied `awarded_bid_cents` is recorded and `required_bond_cents` is recomputed on the final basis — ten percent over the awarded bid rather than over the estimate, again rounded half-up to whole cents. For identical phase data the two bases differ, so the required bond changes at award."

        Design: Difficulty/dual_variant_calc/bond_requirement_provisional_vs_final
        """
        parcel = create_parcel(parcel_name="P1")
        phase = create_phase(parcel["id"], planned_lot_count=10)
        bond = validate_success(api.create_bond(
            {"phase_id": phase["id"], "engineer_estimate_cents": 10000000}, DEV), 201)
        provisional_required = bond["required_bond_cents"]

        awarded = validate_success(api.award_bid(
            bond["id"], {"awarded_bid_cents": 9000000}, DEV))
        assert awarded["status"] == "BID_FINAL"
        assert awarded["awarded_bid_cents"] == 9000000
        # 110% of the 9000000 awarded bid, final basis
        assert awarded["required_bond_cents"] == 9900000
        assert awarded["required_bond_cents"] != provisional_required

    def test_post_bond_at_exact_requirement_boundary(self, api):
        """PRD §3.3: "Posting then moves the bond from `BID_FINAL` to `POSTED`: the supplied `posted_amount_cents` must be at least the current `required_bond_cents` — the boundary is inclusive, an exactly-equal posting succeeds — and anything less is rejected with `ERR_INSUFFICIENT_BOND_POSTED`; the posted amount is stored on `posted_bond_cents`."

        Design: Corner/calculations/bond_post_at_exact_required_amount_accepted
        """
        parcel = create_parcel(parcel_name="BP")
        phase = create_phase(parcel["id"], planned_lot_count=2)
        bond = create_bond(phase["id"])
        award_bid(bond["id"], 9000000)  # required = 9900000

        validate_error(api.post_bond(
            bond["id"], {"posted_amount_cents": 9899999}, DEV),
            ApiErrorId.ERR_INSUFFICIENT_BOND_POSTED)
        posted = validate_success(api.post_bond(
            bond["id"], {"posted_amount_cents": 9900000}, DEV))
        assert posted["status"] == "POSTED"
        assert posted["posted_bond_cents"] == 9900000

    def test_bond_reduction_rejected_when_loan_above_half_commitment(self, api):
        """PRD §3.3: "Reducing a `POSTED` bond moves it to `PARTIALLY_REDUCED` and subtracts the supplied `reduction_amount_cents` from `posted_bond_cents`, but only when three conditions all hold; any violation is rejected with `ERR_BOND_REDUCTION_NOT_ELIGIBLE`."
        PRD §3.3: "First, the parcel's single `ACTIVE` development loan (selected per §3.6; when no such loan exists the gate fails with `ERR_NO_ACTIVE_LOAN`) must carry an `outstanding_balance_cents` of no more than half of `commitment_amount_cents`, the half computed as the commitment times 5000 basis points over ten thousand and the boundary inclusive."

        Design: Corner/errors/error_bond_reduction_not_eligible
        """
        parcel = create_acquired_parcel(parcel_name="BRP")
        phase = create_phase(parcel["id"], planned_lot_count=2)
        bond = create_posted_bond(phase["id"])  # POSTED at 9900000
        loan = create_active_loan(parcel["id"], commitment_amount_cents=2000000)
        # net disbursement 1417875 exceeds half of the 2000000 commitment
        create_funded_draw(loan["id"], 1500000)
        resp = api.reduce_bond(bond["id"], {"reduction_amount_cents": 100000}, DEV)
        validate_error(resp, ApiErrorId.ERR_BOND_REDUCTION_NOT_ELIGIBLE)
