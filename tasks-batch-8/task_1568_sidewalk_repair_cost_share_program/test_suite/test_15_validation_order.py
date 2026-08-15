"""Validation priority ordering, optimistic concurrency control, and
resource-existence errors."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    adjust_appropriation,
    create_extension_payload,
    make_contractor,
    make_contractor_headers,
    make_cycle,
    make_owner,
    make_owner_headers,
    set_clock,
    setup_application,
    setup_delinquent_notice,
    setup_issued_notice,
    setup_sealed_batch,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
FINANCE = TEST_USERS["finance_headers"]
INSP1 = TEST_USERS["inspector_headers"]


class TestPriorityPairs:
    def test_state_beats_fiscal_on_obligate(self, api):
        """PRD §2.7: "When several checks could reject the same request, the
        server evaluates them in a fixed priority order and reports only the
        first failure."
        PRD §2.7: "12. **Priority 11 — fiscal caps, always last.**
        `ERR_PROGRAM_CAP_EXCEEDED` (HTTP 402)"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_obligate
        """
        bundle = setup_application(
            appropriation_cents=100, parcel_number="P-1100",
            segment_code="S-1100-1", owner_name="Mia Maple",
            street_address="13 Maple St", defect_type="VERTICAL_SEPARATION",
            measured_offset_inches=0.75, area_sqft=100, estimated_qty_sqft=100)
        assert bundle["application"]["review_status"] == "SUBMITTED"

        # Both violations hold: state (not APPROVED) and fiscal (60000 > 100).
        resp = api.obligate_application(bundle["application"]["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_APPLICATION_STATE)

    def test_fiscal_fires_when_state_passes(self, api):
        """PRD §3.6: "the fiscal cap, evaluated last and at request time
        against the cycle's current balances, requires the sum of
        `committed_cents` and this application's `provisional_award_cents` not
        to exceed `appropriation_cents` — equality is allowed — else
        `ERR_PROGRAM_CAP_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_obligate
        """
        bundle = setup_application(
            appropriation_cents=100, parcel_number="P-1100",
            segment_code="S-1100-1", owner_name="Mia Maple",
            street_address="13 Maple St", defect_type="VERTICAL_SEPARATION",
            measured_offset_inches=0.75, area_sqft=100, estimated_qty_sqft=100)
        validate_success(api.decide_application(
            bundle["application"]["id"], {"outcome": "APPROVE"}, COORD))

        resp = api.obligate_application(bundle["application"]["id"], FINANCE)
        # With the state precondition satisfied, the fiscal rule fires.
        validate_error(resp, ApiErrorId.ERR_PROGRAM_CAP_EXCEEDED)

    def test_temporal_beats_constraint_on_bid(self, api):
        """PRD §2.7: "When several checks could reject the same request, the
        server evaluates them in a fixed priority order and reports only the
        first failure."
        PRD §3.7: "Bids are accepted only while the batch is
        `SEALED_FOR_BIDDING` (else `ERR_INVALID_BATCH_STATE`) and only while the
        logical clock has not passed the `bid_deadline`, with a bid landing
        exactly at the deadline still timely (else `ERR_BID_DEADLINE_PASSED`)"

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_bid
        """
        bundle = setup_delinquent_notice(
            sweep_clock="2026-09-20T00:00:00Z", parcel_number="P-1200",
            segment_code="S-1200-1", owner_name="Nora Nut",
            street_address="14 Nut St")
        setup_sealed_batch(bundle, "NB-4")
        contractor = make_contractor("Shady Pavers", "L-002", "2026-12-31")
        validate_success(api.suspend_contractor(contractor["id"], COORD))
        set_clock("2026-09-23T00:00:00Z")  # past bid_deadline 2026-09-22

        # Both violations hold: deadline passed AND contractor suspended; the
        # OCC version supplied is current, so the version check cannot mask it.
        resp = api.create_bid(
            {"batch_id": bundle["batch"]["id"], "unit_rate_cents": 900,
             "ramp_flat_fee_cents": 0,
             "expected_batch_version": bundle["batch_version"]},
            make_contractor_headers(contractor["id"]))
        validate_error(resp, ApiErrorId.ERR_BID_DEADLINE_PASSED)

    def test_suspension_fires_when_temporal_passes(self, api):
        """PRD §3.7: "A suspension flips that flag true, after which the
        contractor's bids are rejected with `ERR_CONTRACTOR_SUSPENDED` and it is
        excluded from award eligibility."

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_on_bid
        """
        bundle = setup_delinquent_notice(
            sweep_clock="2026-09-16T00:00:00Z", parcel_number="P-1200",
            segment_code="S-1200-1", owner_name="Nora Nut",
            street_address="14 Nut St")
        setup_sealed_batch(bundle, "NB-4")
        contractor = make_contractor("Shady Pavers", "L-002", "2026-12-31")
        validate_success(api.suspend_contractor(contractor["id"], COORD))

        # Clock is still 2026-09-16 (<= bid_deadline 2026-09-22): only the
        # suspension constraint can fail.
        resp = api.create_bid(
            {"batch_id": bundle["batch"]["id"], "unit_rate_cents": 900,
             "ramp_flat_fee_cents": 0,
             "expected_batch_version": bundle["batch_version"]},
            make_contractor_headers(contractor["id"]))
        validate_error(resp, ApiErrorId.ERR_CONTRACTOR_SUSPENDED)

    def test_existence_beats_state_on_work_item_create(self, api):
        """PRD §2.7: "5. **Priority 4 — existence.** Path identifiers and body
        foreign keys must reference existing resources, validated left-to-right"
        PRD §2.7: "When several checks could reject the same request, the
        server evaluates them in a fixed priority order and reports only the
        first failure."

        Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_work_item_create
        """
        bundle = setup_delinquent_notice(
            sweep_clock="2026-09-20T00:00:00Z", parcel_number="P-1300",
            segment_code="S-1300-1", owner_name="Ora Oak",
            street_address="15 Oak St")
        setup_sealed_batch(bundle, "NB-5")

        # Both violations hold: batch is SEALED (state) and the notice id does
        # not exist (existence); existence wins.
        resp = api.create_work_item(
            {"batch_id": bundle["batch"]["id"],
             "notice_id": NON_EXISTENT_UUID, "scope_sqft": 10,
             "engineer_unit_rate_cents": 1300}, COORD)
        validate_error(resp, ApiErrorId.ERR_REPAIR_NOTICE_NOT_FOUND)

    def test_batch_state_fires_when_existence_passes(self, api):
        """PRD §3.7: "While the batch remains `OPEN_FOR_ITEMS`, a coordinator
        may remove an item — `POOLED → REMOVED`, failing with
        `ERR_INVALID_WORK_ITEM_STATE` or `ERR_INVALID_BATCH_STATE` outside those
        states"
        PRD §3.7: "A coordinator creates a `BatchWorkItem` naming a `batch_id`,
        a `notice_id`, a `scope_sqft` greater than zero, and an
        `engineer_unit_rate_cents` greater than zero. The referenced notice must
        be `DELINQUENT` — pooling is the city-repair path"

        Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_work_item_create
        """
        bundle = setup_delinquent_notice(
            sweep_clock="2026-09-16T00:00:00Z", parcel_number="P-1300",
            segment_code="S-1300-1", owner_name="Ora Oak",
            street_address="15 Oak St")
        setup_sealed_batch(bundle, "NB-5")

        # Second DELINQUENT notice, never pooled: existence passes and the
        # batch-state check is the one that fails.
        other = setup_delinquent_notice(
            sweep_clock="2026-09-16T00:00:00Z", parcel_number="P-1301",
            segment_code="S-1301-1", owner_name="Ora Oak2",
            street_address="16 Oak St")
        resp = api.create_work_item(
            {"batch_id": bundle["batch"]["id"],
             "notice_id": other["notice"]["id"], "scope_sqft": 10,
             "engineer_unit_rate_cents": 1300}, COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_BATCH_STATE)


class TestPriorityOrderingCorner:
    def test_forbidden_role_beats_not_found(self, api):
        """PRD §2.7: "3. **Priority 2 — role authorization.** The caller's role
        must appear in the endpoint's role list, else `ERR_FORBIDDEN_ROLE`."
        PRD §2.7: "When several checks could reject the same request, the
        server evaluates them in a fixed priority order and reports only the
        first failure."

        Design: Corner/validations/forbidden_role_beats_not_found
        """
        resp = api.lock_program_cycle(NON_EXISTENT_UUID, INSP1)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_ownership_mismatch_beats_invalid_state(self, api):
        """PRD §2.7: "4. **Priority 3 — ownership and scope.** Entity-backed
        actors may act only on resources their ownership chain covers, else
        `ERR_OWNERSHIP_MISMATCH`."
        PRD §3.5: "Withdrawal and resubmission from a state the application
        does not occupy, or by anyone but the owning owner, fail with
        `ERR_INVALID_APPLICATION_STATE` and `ERR_OWNERSHIP_MISMATCH`
        respectively."

        Design: Corner/validations/ownership_mismatch_beats_invalid_state
        """
        bundle = setup_application(parcel_number="P-V3", segment_code="S-V3-1",
                                   owner_name="Cat Caper",
                                   street_address="79 Caper St",
                                   estimated_qty_sqft=50)
        app = validate_success(api.withdraw_application(
            bundle["application"]["id"],
            make_owner_headers(bundle["owner"]["id"])))
        assert app["review_status"] == "WITHDRAWN", \
            "the state precondition would fail too"

        owner_b = make_owner("Don Dioon", "80 Dioon St")
        resp = api.withdraw_application(
            app["id"], make_owner_headers(owner_b["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)

    def test_stale_version_beats_bid_deadline(self, api):
        """PRD §2.5: "Submitting a bid requires `expected_batch_version`, the
        client's last observed `version` of the target `BidBatch`. A bid's price
        is computed against the batch's work-item list, and each accepted bid
        creation itself increments the batch's `version`, so a request carrying
        an earlier expected version fails deterministically with
        `ERR_STALE_BATCH_VERSION` (HTTP 412)."
        PRD §2.7: "7. **Priority 6 — optimistic concurrency.** On the three
        OCC-guarded writes of §2.5, the expected-version field must equal the
        parent's current `version`, else the matching stale-version error (HTTP
        412)."

        Design: Corner/validations/stale_version_beats_bid_deadline
        """
        bundle = setup_delinquent_notice(
            sweep_clock="2026-09-16T00:00:00Z", parcel_number="P-V4",
            segment_code="S-V4-1", owner_name="Eve Emu",
            street_address="81 Emu St")
        setup_sealed_batch(bundle, "NB-V4")
        c1 = make_contractor("Acme Paving", "L-001", "2026-12-31")
        c2 = make_contractor("Best Builders", "L-002", "2026-12-31")

        validate_success(api.create_bid(
            {"batch_id": bundle["batch"]["id"], "unit_rate_cents": 1000,
             "ramp_flat_fee_cents": 0,
             "expected_batch_version": bundle["batch_version"]},
            make_contractor_headers(c1["id"])), 201)
        set_clock("2026-09-23T00:00:00Z")  # past bid_deadline too

        resp = api.create_bid(
            {"batch_id": bundle["batch"]["id"], "unit_rate_cents": 900,
             "ramp_flat_fee_cents": 0,
             "expected_batch_version": bundle["batch_version"]},
            make_contractor_headers(c2["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_BATCH_VERSION)


class TestOptimisticConcurrency:
    def test_notice_extension_stale_version(self, api):
        """PRD §2.5: "Extending a notice's deadline requires the request to
        carry `expected_notice_version`, the client's last observed `version` of
        that `RepairNotice`. If the value does not match the notice's current
        `version` — because the notice has been mutated since the client read it
        — the extension is rejected with `ERR_STALE_NOTICE_VERSION` (HTTP 412)"
        PRD §3.3: "Multiple sequential extensions are legitimate — each
        accepted extension adds its days to the `compliance_deadline` and
        increments the notice's `version`"

        Design: Corner/cross_cutting_complexity_layers/occ_notice_extension_stale_version
        """
        bundle = setup_issued_notice(parcel_number="P-X1",
                                     segment_code="S-X1-1", owner_name="Ian Ivy",
                                     street_address="116 Ivy St")
        notice = bundle["notice"]
        assert notice["compliance_deadline"] == "2026-09-15T00:00:00Z"
        notice_v = notice["version"]

        extended = validate_success(api.extend_repair_notice(
            notice["id"], create_extension_payload(10, notice_v), COORD))
        assert extended["compliance_deadline"] == "2026-09-25T00:00:00Z"
        assert extended["version"] == notice_v + 1

        resp = api.extend_repair_notice(
            notice["id"], create_extension_payload(10, notice_v), COORD)
        validate_error(resp, ApiErrorId.ERR_STALE_NOTICE_VERSION)

    def test_bid_stale_batch_version(self, api):
        """PRD §2.5: "Submitting a bid requires `expected_batch_version`, the
        client's last observed `version` of the target `BidBatch`. A bid's price
        is computed against the batch's work-item list, and each accepted bid
        creation itself increments the batch's `version`, so a request carrying
        an earlier expected version fails deterministically with
        `ERR_STALE_BATCH_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_bid_stale_batch_version
        """
        bundle = setup_delinquent_notice(
            sweep_clock="2026-09-16T00:00:00Z", parcel_number="P-X2",
            segment_code="S-X2-1", owner_name="Jen Juniper",
            street_address="117 Juniper St")
        setup_sealed_batch(bundle, "NB-X2")
        c1 = make_contractor("Acme Paving", "L-001", "2026-12-31")
        c2 = make_contractor("Best Builders", "L-002", "2026-12-31")

        bid1 = validate_success(api.create_bid(
            {"batch_id": bundle["batch"]["id"], "unit_rate_cents": 1000,
             "ramp_flat_fee_cents": 0,
             "expected_batch_version": bundle["batch_version"]},
            make_contractor_headers(c1["id"])), 201)
        assert bid1["status"] == "SUBMITTED"

        resp = api.create_bid(
            {"batch_id": bundle["batch"]["id"], "unit_rate_cents": 900,
             "ramp_flat_fee_cents": 0,
             "expected_batch_version": bundle["batch_version"]},
            make_contractor_headers(c2["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_BATCH_VERSION)

    def test_cycle_adjustment_stale_version(self, api):
        """PRD §2.5: "Adjusting a cycle's appropriation requires
        `expected_program_cycle_version`, the client's last observed `version`
        of the `ProgramCycle`. A mismatch with the cycle's current `version` is
        rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_cycle_adjustment_stale_version
        """
        cycle = make_cycle(appropriation_cents=1000000)
        cycle_v = cycle["version"]

        adjusted = validate_success(
            adjust_appropriation(cycle["id"], 50000, cycle_v))
        assert adjusted["appropriation_cents"] == 1050000
        assert adjusted["version"] == cycle_v + 1

        resp = adjust_appropriation(cycle["id"], 50000, cycle_v)
        validate_error(resp, ApiErrorId.ERR_STALE_CYCLE_VERSION)


class TestExistenceErrors:
    def test_get_reads_return_not_found_per_resource(self, api):
        """PRD §2.7: "Path identifiers and body foreign keys must reference
        existing resources, validated left-to-right: path parameters first, then
        body fields in their declaration order. Each resource type has its own
        not-found error — `ERR_PROGRAM_CYCLE_NOT_FOUND`,
        `ERR_PROPERTY_OWNER_NOT_FOUND`, `ERR_PARCEL_NOT_FOUND`,
        `ERR_SEGMENT_NOT_FOUND`, `ERR_DEFECT_NOT_FOUND`,
        `ERR_REPAIR_NOTICE_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`,
        `ERR_BID_BATCH_NOT_FOUND`, `ERR_WORK_ITEM_NOT_FOUND`,
        `ERR_CONTRACTOR_NOT_FOUND`, `ERR_BID_NOT_FOUND`,
        `ERR_FORESTRY_REVIEW_NOT_FOUND`, and `ERR_LIEN_CASE_NOT_FOUND` (all HTTP
        404)."

        Design: Corner/errors/get_reads_return_not_found_per_resource
        """
        checks = [
            (api.get_program_cycle(NON_EXISTENT_UUID, COORD),
             ApiErrorId.ERR_PROGRAM_CYCLE_NOT_FOUND),
            (api.get_parcel(NON_EXISTENT_UUID, COORD),
             ApiErrorId.ERR_PARCEL_NOT_FOUND),
            (api.get_segment(NON_EXISTENT_UUID, COORD),
             ApiErrorId.ERR_SEGMENT_NOT_FOUND),
            (api.get_defect(NON_EXISTENT_UUID, COORD),
             ApiErrorId.ERR_DEFECT_NOT_FOUND),
            (api.get_application(NON_EXISTENT_UUID, COORD),
             ApiErrorId.ERR_APPLICATION_NOT_FOUND),
            (api.get_bid_batch(NON_EXISTENT_UUID, COORD),
             ApiErrorId.ERR_BID_BATCH_NOT_FOUND),
            (api.get_work_item(NON_EXISTENT_UUID, COORD),
             ApiErrorId.ERR_WORK_ITEM_NOT_FOUND),
            (api.get_bid(NON_EXISTENT_UUID, COORD),
             ApiErrorId.ERR_BID_NOT_FOUND),
            (api.get_lien_case(NON_EXISTENT_UUID, COORD),
             ApiErrorId.ERR_LIEN_CASE_NOT_FOUND),
        ]
        for resp, error_id in checks:
            assert resp.json()["response_type"] == "error"
            validate_error(resp, error_id)

    def test_forestry_review_decision_not_found(self, api):
        """PRD §2.7: "Path identifiers and body foreign keys must reference
        existing resources, validated left-to-right: path parameters first, then
        body fields in their declaration order."

        Design: Corner/errors/forestry_review_decision_not_found
        """
        resp = api.decide_forestry_review(
            NON_EXISTENT_UUID, {"decision": "PRUNE_APPROVED"},
            TEST_USERS["forestry_headers"])
        validate_error(resp, ApiErrorId.ERR_FORESTRY_REVIEW_NOT_FOUND)
