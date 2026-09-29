"""Cross-cutting layers: version guards, inclusive thresholds, live derivation.

Two writes in this system silently supersede the state of a parent row, so both
make the client prove it read that parent first. Elsewhere the same posture value
gates two operations differently, one obligation prices held waste while another
prices the treatment committed to it, and a single move of the logical clock
brings two unrelated deadlines due at once.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_assurance,
    assert_cents,
    assert_mass,
    assert_ratio,
    assert_unit_state,
    factories,
    fixtures,
)

DECLARED_CONSTITUENT_PPM = 12000.0
REVISED_CONSTITUENT_PPM = 19000.0


def _profile_resubmitted_after_one_failed_run() -> fixtures.Scenario:
    """A profile whose first laboratory run failed on constituent deviation and
    which the generator has resubmitted with a revised declared concentration.

    The resubmission advances the profile's version, so the version the chemist
    read at submission time is no longer the current one.
    """
    fixtures.set_clock()
    facility = fixtures.create_facility()
    generator = fixtures.create_generator()
    profile = fixtures.create_draft_profile(
        generator["id"],
        facility["id"],
        declared_constituent_ppm=DECLARED_CONSTITUENT_PPM,
    )
    submitted = fixtures.submit_profile(profile["id"], generator["id"])
    fixtures.record_sample(
        profile["id"], submitted["version"], measured_constituent_ppm=20000.0
    )
    failed = fixtures.read_profile(profile["id"])
    resubmitted = fixtures.submit_profile(
        profile["id"],
        generator["id"],
        payload={"revised_declared_constituent_ppm": REVISED_CONSTITUENT_PPM},
    )
    return fixtures.Scenario(
        facility=facility,
        generator=generator,
        profile=profile,
        submitted=submitted,
        failed=failed,
        resubmitted=resubmitted,
    )


def _second_laboratory_run_payload(expected_waste_profile_version: int) -> dict:
    """A run measuring 19100.0 ppm: a 0.0053 deviation from the revised 19000.0."""
    return factories.sample_payload(
        expected_waste_profile_version,
        sample_type="FULL",
        measured_constituent_ppm=19100.0,
        measured_flash_point_c=42.5,
        measured_ph=7.1,
    )


def _tank_with_an_open_repair_order_and_a_one_month_profile() -> fixtures.Scenario:
    """A tank whose air-monitoring reading of 300.0 ppm opened a repair order,
    plus an approved profile that recertifies after a single calendar month."""
    scenario = fixtures.setup_tank_with_repair_order(measured_organic_vapor_ppm=300.0)
    scenario.generator = fixtures.create_generator()
    scenario.profile = fixtures.create_approved_profile(
        scenario.generator["id"],
        scenario.facility["id"],
        profile_overrides={"recertification_months": 1},
    )
    scenario.order = fixtures.read_repair_order(scenario.order["id"])
    return scenario


class TestOptimisticConcurrencyOnSupersedingWrites:
    def test_instrument_posted_against_a_superseded_facility_view_is_refused(self):
        """Posting a financial assurance instrument (`POST /tsdf/financial-assurance-instruments`) requires `expected_facility_version` to equal the target facility's current `version`.
        If `expected_facility_version` does not match, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is written.
        As a cascade, the facility's prior `ACTIVE` instrument moves to `SUPERSEDED`, with its `superseded_by_instrument_id` set to the new instrument's identifier and its `superseded_at` stamped with the current clock instant; the facility's `version` advances; and `posted_assurance_cents` and `assurance_shortfall_cents` are recomputed from the surviving `ACTIVE` instrument alone.
        Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp in the same format that is refreshed whenever any stored or derived property of the row changes, and `version`, an integer that starts at 1 on creation and increments by one on every mutation of the row.

        Design: Corner/cross-cutting complexity layers/instrument_posted_against_a_stale_facility_version_rejected
        """
        fixtures.set_clock()
        facility = fixtures.create_facility()
        assert facility["version"] == 1
        first = fixtures.post_instrument(
            facility["id"],
            face_amount_cents=40_000_000,
            expected_facility_version=facility["version"],
        )
        replacement = factories.instrument_payload(
            facility["id"],
            facility["version"],
            face_amount_cents=90_000_000,
            instrument_type="SURETY_BOND",
            effective_on="2026-07-15",
        )

        stale = api_client.create_instrument(
            replacement, TEST_USERS["compliance_manager_2"]
        )

        validate_error(stale, "ERR_STALE_VERSION")
        assert fixtures.read_instrument(first["id"])["status"] == "ACTIVE"
        after_refusal = fixtures.read_facility(facility["id"])
        assert_assurance(after_refusal, posted_cents=40_000_000)
        assert after_refusal["version"] == 2
        _, meta = validate_paginated(
            api_client.list_instruments(
                TEST_USERS["compliance_manager"],
                params={"facility_id": facility["id"]},
            )
        )
        assert meta["total_count"] == 1, "the refused post must write no instrument"

        replacement["expected_facility_version"] = after_refusal["version"]
        retried = validate_success(
            api_client.create_instrument(
                replacement, TEST_USERS["compliance_manager_2"]
            ),
            expected_status=201,
        )

        assert retried["status"] == "ACTIVE"
        superseded = fixtures.read_instrument(first["id"])
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["superseded_by_instrument_id"] == retried["id"]
        settled = fixtures.read_facility(facility["id"])
        assert_assurance(settled, posted_cents=90_000_000)
        assert settled["version"] == 3

    def test_sample_recorded_against_a_superseded_profile_view_is_refused(self):
        """Recording a verification sample (`POST /tsdf/waste-profiles/{id}/samples`) requires `expected_waste_profile_version` to equal the target profile's current `version`.
        The newest sample supersedes the previous one as the profile's `latest_sample_result` and can drive the profile to `SAMPLE_PASSED`, `SAMPLE_FAILED` or `REJECTED`; a sample written from a stale view of the declared characterisation would be judged against superseded tolerances. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).
        Recording a sample always increments the profile's `sample_attempt_count` by one, sets `latest_sample_result` from the sample's result, and advances the profile's `version`.
        A failing sample that leaves the incremented attempt count below 3 moves the profile from `SUBMITTED` to `SAMPLE_FAILED` and forces `required_sample_type` to `FULL`.
        A passing sample moves the profile from `SUBMITTED` to `SAMPLE_PASSED`.
        The tolerance set is chosen by the profile's `required_sample_type`, and the choice actually made is copied onto the sample as `applied_tolerance_type` so that the decision is auditable after the fact.
        Under a `FULL` tolerance, those three allowances tighten to 0.10, 3.0 degrees Celsius and 0.5 respectively.
        `constituent_deviation_pct` is the absolute difference between `measured_constituent_ppm` and the profile's `declared_constituent_ppm`, divided by the declared concentration or by 1 when the declared concentration is smaller than 1, rounded half up to 4 decimals before any comparison.

        Design: Corner/cross-cutting complexity layers/sample_recorded_against_a_stale_profile_version_rejected
        """
        scenario = _profile_resubmitted_after_one_failed_run()
        assert scenario.failed["status"] == "SAMPLE_FAILED"
        assert scenario.failed["sample_attempt_count"] == 1
        assert scenario.resubmitted["status"] == "SUBMITTED"
        assert scenario.resubmitted["required_sample_type"] == "FULL"
        assert scenario.resubmitted["version"] > scenario.submitted["version"]

        stale = api_client.create_profile_sample(
            scenario.profile["id"],
            _second_laboratory_run_payload(scenario.submitted["version"]),
            TEST_USERS["chemist"],
        )

        validate_error(stale, "ERR_STALE_VERSION")
        after_refusal = fixtures.read_profile(scenario.profile["id"])
        assert after_refusal["sample_attempt_count"] == 1
        assert after_refusal["status"] == "SUBMITTED"
        assert after_refusal["version"] == scenario.resubmitted["version"]
        _, meta = validate_paginated(
            api_client.list_profile_samples(
                scenario.profile["id"], TEST_USERS["chemist"]
            )
        )
        assert meta["total_count"] == 1, "the refused sample must write no row"

        fresh = validate_success(
            api_client.create_profile_sample(
                scenario.profile["id"],
                _second_laboratory_run_payload(scenario.resubmitted["version"]),
                TEST_USERS["chemist"],
            ),
            expected_status=201,
        )

        assert fresh["applied_tolerance_type"] == "FULL"
        assert_ratio(fresh["constituent_deviation_pct"], 0.0053, "constituent_deviation_pct")
        assert fresh["result"] == "PASS"
        settled = fixtures.read_profile(scenario.profile["id"])
        assert settled["sample_attempt_count"] == 2
        assert settled["status"] == "SAMPLE_PASSED"
        assert settled["version"] == scenario.resubmitted["version"] + 1


class TestInclusiveUtilizationThreshold:
    def test_a_unit_at_exactly_nine_tenths_full_refuses_treatment_but_takes_more_waste(self):
        """Otherwise it is `RESTRICTED` when any container in the unit is `DEFICIENT`, or when `utilization_pct` reaches or exceeds 0.9000 — the utilisation threshold is inclusive, so a unit sitting at exactly 0.9000 is restricted.
        `utilization_pct` is stored plus reserved mass divided by `permitted_capacity_kg`, to 4 decimals.
        Container placement requires the unit's posture to be `OPEN` or `RESTRICTED` and is refused when it is `SUSPENDED` or `CLOSED`.
        Treatment batch creation and treatment start both require posture to be exactly `OPEN`.
        Either refusal is `ERR_UNIT_POSTURE_BLOCKED`.
        `container_count` is the number of containers in the unit whose custody is `FILLING`, `SEALED` or `STAGED`.

        Design: Corner/cross-cutting complexity layers/unit_utilization_exactly_at_ninety_percent_restricts_but_still_accepts_waste
        """
        scenario = fixtures.setup_sealed_container(
            unit_overrides={"permitted_capacity_kg": 1000.0},
            declared_quantity_kg=2000.0,
            declared_container_count=8,
            net_weight_kg=900.0,
            container_overrides={"container_type": "TOTE", "capacity_kg": 1000.0},
        )
        crowded = fixtures.read_unit(scenario.unit["id"])
        assert_ratio(crowded["utilization_pct"], 0.9000, "utilization_pct")
        assert_unit_state(crowded, posture="RESTRICTED")

        blocked = api_client.create_treatment_batch(
            factories.treatment_batch_payload(
                scenario.facility["id"],
                scenario.unit["id"],
                [scenario.container["id"]],
                window_start="2026-08-01T00:00:00Z",
                window_end="2026-08-01T12:00:00Z",
            ),
            TEST_USERS["operator"],
        )

        validate_error(blocked, "ERR_UNIT_POSTURE_BLOCKED")
        unstaged = fixtures.read_container(scenario.container["id"])
        assert unstaged["custody_state"] == "SEALED"
        assert unstaged["treatment_batch_id"] is None

        validate_success(
            api_client.create_container(
                factories.container_payload(
                    scenario.line["id"],
                    scenario.unit["id"],
                    net_weight_kg=100.0,
                    capacity_kg=250.0,
                ),
                TEST_USERS["clerk"],
            ),
            expected_status=201,
        )

        filled = fixtures.read_unit(scenario.unit["id"])
        assert_unit_state(
            filled,
            posture="RESTRICTED",
            container_count=2,
            stored_kg=1000.0,
            utilization_pct=1.0000,
        )


class TestTreatmentLiabilityAgainstClosureCost:
    def test_a_planned_batch_adds_its_liability_and_an_abort_gives_it_back(self):
        """`closure_base_cost_cents` is 25,000,000 cents of fixed closure overhead plus 1,800 cents for every kilogram of `held_mass_kg`, that per-kilogram product being rounded half up to whole cents before it is added to the fixed component.
        **Step three** applies the tier's surcharge rate: `closure_cost_estimate_cents` is `closure_base_cost_cents` multiplied by one plus the tier's rate, rounded half up to whole cents.
        `required_assurance_cents` is the sum of `closure_cost_estimate_cents`, the facility's input `post_closure_cost_cents`, `corrective_action_reserve_cents`, and `active_treatment_liability_cents` — the last being the sum of `estimated_treatment_liability_cents` across the facility's batches that are `PLANNED` or `IN_TREATMENT`.
        Three figures are frozen at creation and never recomputed thereafter: `input_mass_kg`, the sum of `net_weight_kg` across the staged containers to 3 decimals; `dominant_compatibility_class`, the compatibility class of the staged container with the greatest `net_weight_kg`, with the lowest container `created_at` breaking a tie; and `estimated_treatment_liability_cents`, `input_mass_kg` multiplied by 220 cents per kilogram and rounded half up to whole cents.
        Creation stages each listed container, raises the unit's `reserved_kg` by the frozen input mass, and raises the facility's `active_treatment_liability_cents` and `required_assurance_cents` by the frozen liability.
        `ABORT` moves the batch to the terminal `ABORTED` and is defined from three source statuses — `PLANNED`, `HELD` and `IN_TREATMENT` — with identical effects in all three: every staged container returns to `SEALED` with `treatment_batch_id` cleared to null, and the batch leaves the unit's `reserved_kg` and the facility's `active_treatment_liability_cents`, so the facility's `required_assurance_cents` returns exactly to its pre-creation value with no rounding drift.

        Design: Corner/cross-cutting complexity layers/assurance_requirement_reconciles_when_a_batch_reserves_treatment_liability
        """
        scenario = fixtures.setup_sealed_container(net_weight_kg=200.0)
        assert_assurance(
            fixtures.read_facility(scenario.facility["id"]),
            required_cents=34_628_000,
            liability_cents=0,
        )

        batch = validate_success(
            api_client.create_treatment_batch(
                factories.treatment_batch_payload(
                    scenario.facility["id"],
                    scenario.unit["id"],
                    [scenario.container["id"]],
                    window_start="2026-08-01T00:00:00Z",
                    window_end="2026-08-01T12:00:00Z",
                ),
                TEST_USERS["operator"],
            ),
            expected_status=201,
        )

        assert_mass(batch["input_mass_kg"], 200.0, "input_mass_kg")
        assert_cents(
            batch["estimated_treatment_liability_cents"],
            44_000,
            "estimated_treatment_liability_cents",
        )
        committed = fixtures.read_facility(scenario.facility["id"])
        assert_assurance(
            committed,
            liability_cents=44_000,
            estimate_cents=26_628_000,
            required_cents=34_672_000,
        )
        assert_unit_state(
            fixtures.read_unit(scenario.unit["id"]), reserved_kg=200.0, stored_kg=200.0
        )
        assert fixtures.read_container(scenario.container["id"])["custody_state"] == "STAGED"

        fixtures.abort_batch(batch["id"])

        released = fixtures.read_container(scenario.container["id"])
        assert released["custody_state"] == "SEALED"
        assert released["treatment_batch_id"] is None
        assert_unit_state(fixtures.read_unit(scenario.unit["id"]), reserved_kg=0.0)
        assert_assurance(
            fixtures.read_facility(scenario.facility["id"]),
            required_cents=34_628_000,
            liability_cents=0,
        )


class TestOneClockMoveBringsTwoDeadlinesDue:
    def test_moving_the_clock_lapses_the_profile_and_makes_the_repair_order_overdue(self):
        """Because these two lapses are derived rather than pushed, they are observable purely by moving the clock: no separate request is needed to expire a permit or a profile.
        Whenever the profile is read or touched and the clock has passed `recertification_due_at`, an `APPROVED` profile is observed as `EXPIRED`.
        Two deadlines are stamped at the same time: `first_attempt_due_at` at 5 days after detection and `repair_due_at` at 15 days after detection.
        `is_overdue` is derived on every read: it is true when the order's `status` is anything other than `REPAIRED` and the current clock instant is strictly later than the applicable deadline — `delayed_due_at` when the order is `DELAYED`, and `repair_due_at` otherwise.
        Otherwise it is `SUSPENDED` when any container in the unit is `CONDEMNED`, or when any emission repair order on the unit is overdue.
        The call mutates no stored row; it merely changes the instant against which derived values are computed on the next read.

        Design: Corner/cross-cutting complexity layers/clock_move_activates_profile_expiry_and_repair_overdue_together
        """
        scenario = _tank_with_an_open_repair_order_and_a_one_month_profile()
        assert scenario.profile["status"] == "APPROVED"
        assert scenario.profile["recertification_due_at"].startswith("2026-09-01")
        assert scenario.order["status"] == "OPEN"
        assert scenario.order["is_overdue"] is False
        assert scenario.order["repair_due_at"].startswith("2026-08-16")
        assert_unit_state(fixtures.read_unit(scenario.unit["id"]), posture="OPEN")
        version_before = scenario.profile["version"]

        fixtures.set_clock("2026-09-02T00:00:00Z")

        lapsed = fixtures.read_profile(scenario.profile["id"])
        assert lapsed["status"] == "EXPIRED"
        assert lapsed["version"] == version_before
        overdue = fixtures.read_repair_order(scenario.order["id"])
        assert overdue["is_overdue"] is True
        assert overdue["status"] == "OPEN"
        assert_unit_state(fixtures.read_unit(scenario.unit["id"]), posture="SUSPENDED")
