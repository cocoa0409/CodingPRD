"""Closing out at harvest and reconciling the tag inventory against the books."""
from test_helpers import (
    ApiErrorId,
    DEFAULT_SERIAL_START,
    apply_device,
    approve_reconciliation_run,
    assert_same_instant,
    assert_tag_lot_partition,
    create_active_premises,
    create_approved_supplier,
    enroll_producer,
    issue_lot,
    make_harvest_operator_headers,
    make_producer_headers,
    make_program_admin_headers,
    open_reconciliation_run,
    read_animal,
    read_premises,
    read_producer,
    read_supplier,
    read_tag,
    read_tag_lot,
    register_producer,
    report_defects,
    retire_tag_payload,
    setup_harvest_ready_animal,
    setup_lot_scenario,
    sightings_of_animal,
    submit_reconciliation_payload,
    submit_reconciliation_run,
    tag_of_animal,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = make_program_admin_headers("admin-reg")


class TestBookBalanceBases:
    def test_cow_calf_premises_books_by_the_as_issued_basis(self, api):
        """PRD §3.8: "The **book balance** is computed under one of two bases, and the run's `basis` is selected from the premises' `operation_type` rather than from anything in the request. Cow-calf and feedlot operations record a `basis` of `AS_ISSUED`; markets and harvest facilities record a `basis` of `AS_SIGHTED`. Either way the lots considered are those whose `premises_id` is this premises and whose `status` is `ISSUED`, `ACTIVE` or `DEPLETED`; recalled and voided lots are excluded from both bases. Under `AS_ISSUED`, the book follows the devices: the `book_unapplied_count` is the sum, over those lots, of each lot's `quantity` less its `applied_count`, less its `retired_count`, less its `replaced_count`, less its `voided_count`. Under `AS_SIGHTED`, the book follows the events: the count of non-reversed `TAG_APPLIED` sightings whose `premises_id` is this premises and whose `observed_at` falls between the very start of `period_start` and the very end of `period_end` inclusive is subtracted from the plain sum of those lots' `quantity` values, ignoring the lot counters entirely."
        PRD §3.8: "The signed `variance_count` is `physical_unapplied_count` less `book_unapplied_count`."

        Design: Difficulty/dual_variant_calc/book_balance_as_issued_vs_as_sighted_diverge
        """
        world = _two_basis_world()

        run = open_reconciliation_run(
            world["cow_calf"]["id"], world["producer"]["id"], "2026-08-01", "2026-08-31"
        )
        submitted = submit_reconciliation_run(run["id"], world["producer"]["id"], 8)

        assert submitted["basis"] == "AS_ISSUED"
        assert submitted["book_unapplied_count"] == 8, (
            "the lot issued here is charged 2 applications wherever they were observed"
        )
        assert submitted["variance_count"] == 0

    def test_market_premises_books_by_the_as_sighted_basis(self, api):
        """PRD §3.8: "The **book balance** is computed under one of two bases, and the run's `basis` is selected from the premises' `operation_type` rather than from anything in the request. Cow-calf and feedlot operations record a `basis` of `AS_ISSUED`; markets and harvest facilities record a `basis` of `AS_SIGHTED`. Either way the lots considered are those whose `premises_id` is this premises and whose `status` is `ISSUED`, `ACTIVE` or `DEPLETED`; recalled and voided lots are excluded from both bases. Under `AS_ISSUED`, the book follows the devices: the `book_unapplied_count` is the sum, over those lots, of each lot's `quantity` less its `applied_count`, less its `retired_count`, less its `replaced_count`, less its `voided_count`. Under `AS_SIGHTED`, the book follows the events: the count of non-reversed `TAG_APPLIED` sightings whose `premises_id` is this premises and whose `observed_at` falls between the very start of `period_start` and the very end of `period_end` inclusive is subtracted from the plain sum of those lots' `quantity` values, ignoring the lot counters entirely."
        PRD §3.8: "The two bases return different integers for the same underlying data whenever a device issued to one premises is applied at a sister premises inside the same producer's operation — `AS_ISSUED` still charges the device to the premises it was issued to, while `AS_SIGHTED` charges it only to the premises where the application was observed."

        Design: Difficulty/dual_variant_calc/book_balance_as_issued_vs_as_sighted_diverge
        """
        world = _two_basis_world()

        run = open_reconciliation_run(
            world["market"]["id"], world["producer"]["id"], "2026-08-01", "2026-08-31"
        )
        submitted = submit_reconciliation_run(run["id"], world["producer"]["id"], 5)

        assert submitted["basis"] == "AS_SIGHTED"
        assert submitted["book_unapplied_count"] == 5, (
            "10 issued here less the five applications observed here"
        )
        assert submitted["variance_count"] == 0

        market_lot = read_tag_lot(world["market_lot"]["id"])
        assert market_lot["applied_count"] == 3, (
            "the device-following basis would have read 7 for this premises, not 5"
        )
        assert read_tag_lot(world["cow_calf_lot"]["id"])["unapplied_count"] == 8

    def test_recalled_lots_are_outside_the_book_balance_input_set(self, api):
        """PRD §3.8: "Either way the lots considered are those whose `premises_id` is this premises and whose `status` is `ISSUED`, `ACTIVE` or `DEPLETED`; recalled and voided lots are excluded from both bases."
        PRD §3.2: "Both of those transitions carry the same collateral consequence: every tag lot belonging to that supplier whose status is `ISSUED` or `ACTIVE` transitions to `RECALLED`."
        PRD §3.8: "The `variance_pct` is 100.0 multiplied by the absolute value of `variance_count`, divided by the greater of 1 and `book_unapplied_count`, rounded half up to two decimal places."

        Design: Corner/calculations/book_balance_excludes_recalled_lots
        """
        producer = register_producer(legal_name="Filter Co", state_code="NM")
        premises = create_active_premises(
            producer["id"], operation_type="COW_CALF", state_code="NM", capacity=60
        )
        first_supplier = create_approved_supplier(company_name="AllFlex North")
        recalled_lot = issue_lot(
            first_supplier["id"], premises["id"], DEFAULT_SERIAL_START, 40
        )
        second_supplier = create_approved_supplier(company_name="Y-Tex Devices")
        surviving_lot = issue_lot(second_supplier["id"], premises["id"], 200_000_000_001, 10)

        suspended = report_defects(first_supplier["id"], 3)
        assert suspended["conformance_score"] == 64.00, "100.00 - 12.0 * (3 / max(1.0, 0.04))"
        assert suspended["status"] == "SUSPENDED"
        assert read_tag_lot(recalled_lot["id"])["status"] == "RECALLED"
        assert read_tag_lot(surviving_lot["id"])["status"] == "ISSUED"

        run = open_reconciliation_run(premises["id"], producer["id"], "2026-08-01", "2026-08-31")
        submitted = submit_reconciliation_run(run["id"], producer["id"], 10)

        assert submitted["basis"] == "AS_ISSUED"
        assert submitted["book_unapplied_count"] == 10, "only the surviving lot books"
        assert submitted["variance_count"] == 0
        assert submitted["variance_pct"] == 0.00

    def test_zero_book_balance_uses_the_denominator_guard(self, api):
        """PRD §3.8: "The `variance_pct` is 100.0 multiplied by the absolute value of `variance_count`, divided by the greater of 1 and `book_unapplied_count`, rounded half up to two decimal places. Only this run's own two counts feed the calculation; earlier runs are never netted in."
        PRD §3.8: "Submitting the count is likewise the owning producer's act, available only from `DRAFT`, and supplies the `physical_unapplied_count` of devices actually found on hand, which must be at least 0. The run moves `DRAFT → SUBMITTED`, records `submitted_by_user_id`, and computes the book side of the comparison."

        Design: Corner/calculations/variance_pct_uses_denominator_guard_when_book_balance_is_zero
        """
        producer = register_producer(legal_name="Zero Book Co", state_code="NM")
        premises = create_active_premises(
            producer["id"], operation_type="FEEDLOT", state_code="NM", capacity=10
        )

        run = open_reconciliation_run(premises["id"], producer["id"], "2026-08-01", "2026-08-31")
        submitted = submit_reconciliation_run(run["id"], producer["id"], 3)

        assert submitted["book_unapplied_count"] == 0
        assert submitted["variance_count"] == 3
        assert submitted["variance_pct"] == 300.00, "the greater of 1 and 0 guards the division"
        assert submitted["status"] == "SUBMITTED", "the branch is only taken at adjudication"


class TestVarianceAdjudication:
    def test_variance_of_exactly_half_a_percent_sits_inside_tolerance(self, api):
        """PRD §3.8: "The signed `variance_count` is `physical_unapplied_count` less `book_unapplied_count`. The `variance_pct` is 100.0 multiplied by the absolute value of `variance_count`, divided by the greater of 1 and `book_unapplied_count`, rounded half up to two decimal places."
        PRD §3.8: "When `variance_pct` is at most 0.50 — a variance of exactly 0.50 percent is inside tolerance — the run moves `SUBMITTED → APPROVED`, and if the premises was sitting in `registration_status` `SUSPENDED` it is reinstated to `ACTIVE`, recomputing the owning producer's `enrolled_head_count` and `incentive_tier`."

        Design: Difficulty/boundary_precision_check/variance_pct_exactly_tolerance_approves_without_suspension
        """
        scenario = setup_lot_scenario(
            operation_type="COW_CALF", state_code="NM", capacity=400, quantity=200,
            legal_name="Cimarron Cattle",
        )
        run = open_reconciliation_run(
            scenario["premises"]["id"], scenario["producer"]["id"], "2026-08-01", "2026-08-31"
        )
        submitted = submit_reconciliation_run(run["id"], scenario["producer"]["id"], 199)

        assert submitted["variance_count"] == -1
        assert submitted["variance_pct"] == 0.50

    def test_run_inside_tolerance_approves_and_leaves_registration_active(self, api):
        """PRD §3.8: "Adjudication belongs to the state and branches on a single boundary. Approving a run is available only from `SUBMITTED`, records `approved_by_user_id`, and then takes one of two disjoint paths."
        PRD §3.8: "When `variance_pct` is at most 0.50 — a variance of exactly 0.50 percent is inside tolerance — the run moves `SUBMITTED → APPROVED`, and if the premises was sitting in `registration_status` `SUSPENDED` it is reinstated to `ACTIVE`, recomputing the owning producer's `enrolled_head_count` and `incentive_tier`."

        Design: Difficulty/boundary_precision_check/variance_pct_exactly_tolerance_approves_without_suspension
        """
        scenario = setup_lot_scenario(
            operation_type="COW_CALF", state_code="NM", capacity=400, quantity=200,
            legal_name="Cimarron Cattle",
        )
        run = open_reconciliation_run(
            scenario["premises"]["id"], scenario["producer"]["id"], "2026-08-01", "2026-08-31"
        )
        submit_reconciliation_run(run["id"], scenario["producer"]["id"], 199)

        approved = approve_reconciliation_run(run["id"])
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "saho-1"
        assert read_premises(scenario["premises"]["id"])["registration_status"] == "ACTIVE", (
            "no suspension cascade fires inside tolerance"
        )

    def test_variance_flag_suspends_the_premises_and_lapses_the_enrolment(self, api):
        """PRD §3.8: "When `variance_pct` exceeds 0.50 the run moves `SUBMITTED → VARIANCE_FLAGGED` and Cascade D runs in three hops: hop one records `approved_by_user_id` and flags the run; hop two suspends the target premises, moving its `registration_status` from `ACTIVE` to `SUSPENDED`, which blocks tag application, movement reporting and lot issuance there with `ERR_PREMISES_NOT_ACTIVE`; hop three re-derives the owning producer, recomputing `enrolled_head_count` without the suspended premises' contribution and re-deriving `incentive_tier`, and lapsing the producer's `enrollment_status` from `ENROLLED` to `LAPSED` if no `ACTIVE` premises remains."
        PRD §3.1: "Enrolment can also be lost without any producer action: when a variance-flagged reconciliation suspends the producer's last remaining `ACTIVE` premises, the producer's `enrollment_status` moves from `ENROLLED` to `LAPSED`, its `enrolled_head_count` is recomputed to 0 and its `incentive_tier` falls to `TIER_0`, and further incentive accrual is blocked with `ERR_PRODUCER_NOT_ENROLLED` until the producer re-enrols."

        Design: Corner/state_machines/variance_flag_cascade_suspends_premises_and_lapses_enrolled_producer
        """
        scenario = setup_lot_scenario(
            operation_type="COW_CALF", state_code="NE", capacity=150, quantity=100,
            legal_name="Lapse Ranch",
        )
        enrolled = enroll_producer(scenario["producer"]["id"])
        assert enrolled["enrollment_status"] == "ENROLLED"

        run = open_reconciliation_run(
            scenario["premises"]["id"], scenario["producer"]["id"], "2026-08-01", "2026-08-31"
        )
        submitted = submit_reconciliation_run(run["id"], scenario["producer"]["id"], 90)
        assert submitted["variance_pct"] == 10.00
        assert submitted["variance_count"] == -10

        flagged = approve_reconciliation_run(run["id"])
        assert flagged["status"] == "VARIANCE_FLAGGED"

        assert read_premises(scenario["premises"]["id"])["registration_status"] == "SUSPENDED"
        producer_after = read_producer(scenario["producer"]["id"])
        assert producer_after["enrollment_status"] == "LAPSED"
        assert producer_after["enrolled_head_count"] == 0
        assert producer_after["incentive_tier"] == "TIER_0"


class TestReconciliationRunLifecycle:
    def test_overlapping_new_run_supersedes_the_draft_which_can_no_longer_submit(self, api):
        """PRD §3.8: "Opening a run also supersedes stale work: any existing `DRAFT` run on the same premises whose period overlaps the new one transitions to `SUPERSEDED`, which is terminal — a superseded run can never be submitted, and the attempt returns `ERR_INVALID_STATE`."
        PRD §3.1: "Premises can be listed and narrowed by `producer_id`, `state_code`, `operation_type`, `registration_status` and `health_status`; each producer's accrued awards can be listed through its own reverse-lookup listing, optionally narrowed by award `status`; and each premises exposes its own reconciliation history, likewise narrowable by run `status`."

        Design: Corner/state_machines/overlapping_new_run_supersedes_draft_run_which_can_no_longer_submit
        """
        producer = register_producer(legal_name="Supersede Co", state_code="NM")
        premises = create_active_premises(producer["id"], state_code="NM", capacity=10)

        first = open_reconciliation_run(premises["id"], producer["id"], "2026-08-01", "2026-08-31")
        second = open_reconciliation_run(premises["id"], producer["id"], "2026-08-15", "2026-09-15")

        resp = api.submit_reconciliation_run(
            first["id"], submit_reconciliation_payload(0), make_producer_headers(producer["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        rows, meta = validate_paginated(
            api.list_premises_reconciliation_runs(premises["id"], ADMIN)
        )
        assert meta["total_count"] == 2
        by_id = {row["id"]: row for row in rows}
        assert by_id[first["id"]]["status"] == "SUPERSEDED"
        assert by_id[second["id"]]["status"] == "DRAFT"

    def test_a_producer_cannot_submit_another_producers_run(self, api):
        """PRD §2.1: "Ownership enforcement covers exactly twelve write operations: `POST /premises`, `POST /producers/{id}/enroll`, `POST /tag-lots`, `POST /tag-lots/{id}/apply-tag`, `POST /tags/{id}/replace`, `POST /tags/{id}/retire`, `POST /movement-events`, `POST /movement-events/{id}/receive`, `POST /movement-events/{id}/correct`, `POST /hold-orders/{id}/appeal`, `POST /reconciliation-runs`, and `POST /reconciliation-runs/{id}/submit`. An entity-backed role acting on a resource that belongs to a different entity instance receives `ERR_NOT_RESOURCE_OWNER`."
        PRD §3.8: "Submitting the count is likewise the owning producer's act, available only from `DRAFT`, and supplies the `physical_unapplied_count` of devices actually found on hand, which must be at least 0. The run moves `DRAFT → SUBMITTED`, records `submitted_by_user_id`, and computes the book side of the comparison."

        Design: Corner/validations/producer_cannot_submit_another_producers_reconciliation_run
        """
        owner = register_producer(legal_name="Owner A")
        stranger = register_producer(legal_name="Owner B")
        premises = create_active_premises(owner["id"], capacity=10)
        run = open_reconciliation_run(premises["id"], owner["id"], "2026-08-01", "2026-08-31")

        resp = api.submit_reconciliation_run(
            run["id"], submit_reconciliation_payload(0), make_producer_headers(stranger["id"])
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)

        rows, _meta = validate_paginated(
            api.list_premises_reconciliation_runs(premises["id"], ADMIN)
        )
        assert rows[0]["status"] == "DRAFT"
        assert rows[0]["submitted_by_user_id"] is None


class TestRetirementCascade:
    def test_retirement_retires_the_device_shifts_the_lot_and_harvests_the_animal(self, api):
        """PRD §3.8: "Success runs Cascade B through four hops. Hop one retires the device itself: `retired_at` is stamped from the logical clock, `tag_returned` and `carcass_ref` are recorded, and `device_status` moves `APPLIED → RETIRED`. Hop two shifts the lot: because a device retired, the lot's `applied_count` falls by one and its `retired_count` rises by one, and if the lot's `unapplied_count` is now 0 the lot moves `ACTIVE → DEPLETED`."
        PRD §3.8: "Alongside the cascade, a `HARVEST` sighting is appended with `observed_at` equal to `harvested_at` and `premises_id` equal to the harvest premises, which re-projects the animal from `ACTIVE` to `HARVESTED`. A harvested animal keeps `current_premises_id` at the harvest premises but stops counting toward that premises' `animal_count`, so the head count falls by one and the owning producer's `enrolled_head_count` and `incentive_tier` are re-derived."

        Design: Difficulty/transitive_cascade/retire_cascade_tag_lot_supplier_suspension_recalls_lots
        """
        scenario = setup_harvest_ready_animal(lot_quantity=4000, defect_count=4)
        harvest_premises_id = scenario["harvest_premises"]["id"]

        retired = validate_success(
            api.retire_tag(
                scenario["tag"]["id"],
                retire_tag_payload(
                    harvest_premises_id,
                    "2026-08-04T00:00:00Z",
                    carcass_ref="CARC-00417",
                    tag_returned=False,
                ),
                make_harvest_operator_headers(harvest_premises_id),
            )
        )
        assert retired["device_status"] == "RETIRED"
        assert_same_instant(retired["retired_at"], "2026-08-04T00:00:00Z", "retired_at")
        assert read_tag(scenario["tag"]["id"])["device_status"] == "RETIRED"

        lot_after = read_tag_lot(scenario["lot"]["id"])
        assert lot_after["applied_count"] == 0
        assert lot_after["retired_count"] == 1
        assert_tag_lot_partition(lot_after)

        animal_after = read_animal(scenario["animal"]["id"])
        assert animal_after["lifecycle_status"] == "HARVESTED"

        history = sightings_of_animal(scenario["animal"]["id"])
        assert history[-1]["sequence_no"] == 4
        assert history[-1]["sighting_type"] == "HARVEST"
        assert history[-1]["premises_id"] == harvest_premises_id

        assert read_premises(harvest_premises_id)["animal_count"] == 0

    def test_retirement_rederives_the_supplier_and_suspends_it_recalling_its_lots(self, api):
        """PRD §3.8: "Hop three re-derives the supplier: because the lot counters changed, the supplier's `retired_tag_count` is recomputed, and its `retired_returned_count` is recomputed as well whenever `tag_returned` was true, which re-derives `conformance_score`, `probation` and `issuance_cap`. Hop four applies the discipline: a recomputed score below 70.00 moves an `APPROVED` supplier to `SUSPENDED`, recalling that supplier's `ISSUED` and `ACTIVE` lots as described in Section 3.2."
        PRD §3.2: "The second is device retention: when the supplier's `retired_tag_count` is zero the retention rate is taken as 1.0000, giving a brand-new supplier full credit rather than a zero-over-zero penalty; otherwise it is `retired_returned_count` divided by `retired_tag_count`, rounded half up to four decimal places."
        PRD §3.2: "The raw score is 100.00 less 12.0 multiplied by defects per thousand, less 20.0 multiplied by the shortfall of the retention rate below 1.0000; the result is clamped to lie no lower than 0.00 and no higher than 100.00, then rounded half up to two decimal places."

        Design: Difficulty/transitive_cascade/retire_cascade_tag_lot_supplier_suspension_recalls_lots
        """
        scenario = setup_harvest_ready_animal(lot_quantity=4000, defect_count=4)
        assert scenario["supplier_before_retire"]["conformance_score"] == 88.00
        assert scenario["supplier_before_retire"]["status"] == "APPROVED"

        harvest_premises_id = scenario["harvest_premises"]["id"]
        validate_success(
            api.retire_tag(
                scenario["tag"]["id"],
                retire_tag_payload(
                    harvest_premises_id,
                    "2026-08-04T00:00:00Z",
                    carcass_ref="CARC-00417",
                    tag_returned=False,
                ),
                make_harvest_operator_headers(harvest_premises_id),
            )
        )

        supplier_after = read_supplier(scenario["supplier"]["id"])
        assert supplier_after["retired_tag_count"] == 1
        assert supplier_after["retired_returned_count"] == 0
        # 100.00 - 12.0 * (4 / 4.0) - 20.0 * (1.0000 - 0.0000)
        assert supplier_after["conformance_score"] == 68.00
        assert supplier_after["status"] == "SUSPENDED"
        assert supplier_after["probation"] is True
        assert supplier_after["issuance_cap"] == 0

        assert read_tag_lot(scenario["lot"]["id"])["status"] == "RECALLED"

    def test_retirement_referential_rules_reject_wrong_premises_and_wrong_type(self, api):
        """PRD §3.8: "Retirement is available only while the device is `APPLIED`. The tagged animal must be `ACTIVE` and must currently stand at the harvest premises — its `current_premises_id` must equal `harvest_premises_id`, else `ERR_ANIMAL_NOT_AT_PREMISES`. The harvest premises must have `operation_type` `HARVEST_FACILITY`, else `ERR_NOT_HARVEST_FACILITY`; it must be `ACTIVE` in registration; and it must not be `QUARANTINED`."

        Design: Corner/validations/retirement_referential_rules_reject_wrong_premises_and_wrong_type
        """
        producer = register_producer(legal_name="Retire Co", state_code="NE")
        source = create_active_premises(
            producer["id"], operation_type="COW_CALF", state_code="NE", capacity=10
        )
        harvest = create_active_premises(
            producer["id"], operation_type="HARVEST_FACILITY", state_code="NE", capacity=10
        )
        supplier = create_approved_supplier(company_name="Y-Tex Devices")
        lot = issue_lot(supplier["id"], source["id"], DEFAULT_SERIAL_START, 10)
        animal = apply_device(lot["id"], producer["id"], DEFAULT_SERIAL_START, source["id"])
        tag = tag_of_animal(animal["id"])

        not_at_premises = api.retire_tag(
            tag["id"],
            retire_tag_payload(harvest["id"], "2026-08-01T00:00:00Z", carcass_ref="CARC-1"),
            make_harvest_operator_headers(harvest["id"]),
        )
        validate_error(
            not_at_premises, ApiErrorId.ERR_ANIMAL_NOT_AT_PREMISES, expected_status=422
        )

        wrong_type = api.retire_tag(
            tag["id"],
            retire_tag_payload(source["id"], "2026-08-01T00:00:00Z", carcass_ref="CARC-1"),
            make_harvest_operator_headers(source["id"]),
        )
        validate_error(wrong_type, ApiErrorId.ERR_NOT_HARVEST_FACILITY, expected_status=422)

        tag_after = read_tag(tag["id"])
        assert tag_after["device_status"] == "APPLIED"
        assert tag_after["retired_at"] is None
        assert read_animal(animal["id"])["lifecycle_status"] == "ACTIVE"


def _two_basis_world() -> dict:
    """One producer owning a COW_CALF premises and a MARKET premises, each issued
    its own ten-device lot, with every application observed at the MARKET premises."""
    producer = register_producer(legal_name="Cedar Ridge Cattle", state_code="TX")
    cow_calf = create_active_premises(
        producer["id"], operation_type="COW_CALF", state_code="TX", capacity=100
    )
    market = create_active_premises(
        producer["id"], operation_type="MARKET", state_code="TX", capacity=100
    )
    supplier = create_approved_supplier(company_name="AllFlex North")
    cow_calf_lot = issue_lot(supplier["id"], cow_calf["id"], DEFAULT_SERIAL_START, 10)
    market_lot = issue_lot(supplier["id"], market["id"], DEFAULT_SERIAL_START + 10, 10)

    for offset in (0, 1):
        apply_device(
            cow_calf_lot["id"], producer["id"], DEFAULT_SERIAL_START + offset, market["id"]
        )
    for offset in (10, 11, 12):
        apply_device(
            market_lot["id"], producer["id"], DEFAULT_SERIAL_START + offset, market["id"]
        )

    return {
        "producer": producer,
        "cow_calf": cow_calf,
        "market": market,
        "supplier": supplier,
        "cow_calf_lot": cow_calf_lot,
        "market_lot": market_lot,
    }
