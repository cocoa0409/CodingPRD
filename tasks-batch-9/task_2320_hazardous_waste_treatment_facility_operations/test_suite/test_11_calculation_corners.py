"""Derived-figure corners: laboratory tolerance evaluation, receipt discrepancy
ranking and charge summation, reliability input filtering, biennial report
scoping, compatibility segregation and the corrective-action projection.

Every expected number is recomputed here from the arithmetic the PRD states,
step by step, so the test fails when the server takes a different route to a
coincidentally similar figure.
"""

from decimal import ROUND_HALF_UP, Decimal

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    TEST_USERS,
    assert_cents,
    assert_mass,
    assert_ratio,
    assert_unit_state,
)
from test_helpers.api_client import api_client
from test_helpers.factories import (
    container_payload,
    finding_payload,
    finding_status_payload,
    manifest_line_payload,
    receipt_line,
    receive_payload,
    sample_payload,
)
from test_helpers.fixtures import (
    create_approved_profile,
    create_draft_profile,
    create_facility,
    create_funded_facility,
    create_generator,
    create_manifest,
    create_storage_unit,
    certify_manifest,
    place_container,
    read_facility,
    read_generator,
    read_lines,
    read_manifest,
    read_profile,
    read_unit,
    receive_manifest,
    record_sample,
    set_clock,
    submit_profile,
)

CENT = Decimal("1")
FOUR_DECIMALS = Decimal("0.0001")


def _round_half_up_cents(raw: Decimal) -> int:
    """Money is a whole number of cents, rounded half up with ties away from zero."""
    return int(raw.quantize(CENT, rounding=ROUND_HALF_UP))


def _assurance_figures(held_mass_kg: str, post_closure_cost_cents: int, snc_count: int):
    """The six assurance figures of an inventory-free facility, in the stated order.

    Returns (closure_base_cost_cents, assurance_tier, closure_cost_estimate_cents,
    corrective_action_reserve_cents, required_assurance_cents).
    """
    # Step one: 25,000,000 cents of fixed closure overhead plus 1,800 cents for
    # every kilogram of held mass, that product rounded half up before it is added.
    per_kilogram = _round_half_up_cents(Decimal(held_mass_kg) * Decimal(1800))
    base = 25_000_000 + per_kilogram
    # Step two: the tier is keyed on the pre-surcharge base cost and nothing else.
    if base < 30_000_000:
        tier, rate = "TIER_1", Decimal("0.05")
    elif base < 60_000_000:
        tier, rate = "TIER_2", Decimal("0.10")
    else:
        tier, rate = "TIER_3", Decimal("0.18")
    # Step three: the base cost multiplied by one plus the tier's rate, rounded half up.
    estimate = _round_half_up_cents(Decimal(base) * (Decimal(1) + rate))
    # Step four: 5,000,000 cents for each counted significant-non-complier finding.
    reserve = 5_000_000 * snc_count
    # Step five: estimate plus the post-closure input plus the reserve plus the
    # active treatment liability, which is zero while no batch is scheduled.
    required = estimate + post_closure_cost_cents + reserve + 0
    return base, tier, estimate, reserve, required


class TestSampleToleranceEvaluation:
    def test_flash_point_breach_is_reported_ahead_of_the_ph_breach(self):
        """A laboratory run that breaches both the flash point and the pH must name
        the flash point, because the checks run in a fixed order and the first
        breach wins; the passing constituent term is still published.

        "The three tolerance checks are then evaluated in a fixed order and the **first breach wins**, naming itself in `failure_reason_code`: first the constituent deviation, which fails with `CONSTITUENT_DEVIATION` when it is strictly greater than the applied constituent allowance; then the flash point, which fails with `FLASH_POINT_DEVIATION` when the absolute difference between `measured_flash_point_c` and `declared_flash_point_c` is strictly greater than the applied flash-point allowance; then the pH, which fails with `PH_DEVIATION` when the absolute difference between `measured_ph` and `declared_ph` is strictly greater than the applied pH allowance."

        "`constituent_deviation_pct` is the absolute difference between `measured_constituent_ppm` and the profile's `declared_constituent_ppm`, divided by the declared concentration or by 1 when the declared concentration is smaller than 1, rounded half up to 4 decimals before any comparison."

        "A failing sample that leaves the incremented attempt count below 3 moves the profile from `SUBMITTED` to `SAMPLE_FAILED` and forces `required_sample_type` to `FULL`."

        Design: Corner/calculations/sample_evaluation_reports_the_first_breach_in_fixed_order
        """
        set_clock()
        facility = create_facility()
        generator = create_generator()
        profile = create_draft_profile(
            generator["id"],
            facility["id"],
            declared_constituent_ppm=12000.0,
            declared_flash_point_c=42.0,
            declared_ph=7.0,
        )
        submitted = submit_profile(profile["id"], generator["id"])
        # A generator with no closed manifest reads 100 on the rolling score and the
        # profile has never been sampled, so the laboratory is told FINGERPRINT.
        assert submitted["required_sample_type"] == "FINGERPRINT"

        response = api_client.create_profile_sample(
            profile["id"],
            sample_payload(
                submitted["version"],
                sample_type="FINGERPRINT",
                measured_constituent_ppm=12500.0,
                measured_flash_point_c=50.0,
                measured_ph=9.0,
            ),
            TEST_USERS["chemist"],
        )
        sample = validate_success(response, expected_status=201)

        # |12500.0 - 12000.0| / 12000.0 rounded half up to four decimals.
        expected_deviation = float(
            (Decimal("500.0") / Decimal("12000.0")).quantize(
                FOUR_DECIMALS, rounding=ROUND_HALF_UP
            )
        )
        assert_ratio(
            sample["constituent_deviation_pct"], expected_deviation, "constituent_deviation_pct"
        )
        # The tolerances actually applied are the FINGERPRINT set the profile asked
        # for: 0.15 on the constituent, 5.0 C on the flash point and 1.0 on the pH.
        assert sample["applied_tolerance_type"] == "FINGERPRINT"
        # The constituent term clears 0.15, the flash point differs by 8.0 C against
        # a 5.0 C allowance, and the pH differs by 2.0 against a 1.0 allowance.
        assert sample["result"] == "FAIL"
        assert sample["failure_reason_code"] == "FLASH_POINT_DEVIATION"
        assert sample["failure_reason_code"] != "PH_DEVIATION"

        after = read_profile(profile["id"])
        assert after["status"] == "SAMPLE_FAILED"
        assert after["sample_attempt_count"] == 1
        assert after["latest_sample_result"] == "FAIL"
        # One failure short of the three-attempt ceiling escalates the scrutiny.
        assert after["required_sample_type"] == "FULL"


class TestReceiptDiscrepancyRanking:
    def test_count_mismatch_outranks_a_significant_quantity_shortfall(self):
        """Two lines fail differently in one receipt — a containerised line short a
        drum at zero quantity variance, and a bulk line ten percent light — and the
        manifest must report the higher-ranked count mismatch while the provisional
        charge sums per-line figures that were each rounded first.

        "The manifest's `discrepancy_type` is the highest-priority `significance` among its lines, ranked `UNDOCUMENTED` above `COUNT_MISMATCH`, `COUNT_MISMATCH` above `QUANTITY_SIGNIFICANT`, and `QUANTITY_SIGNIFICANT` above `NONE`."

        "Otherwise, a containerised line whose `received_container_count` differs from its `declared_container_count` takes a `significance` of `COUNT_MISMATCH` — this check applies only when `is_bulk` is false, and it fires even when the weighed quantity matches exactly."

        "The manifest total is the sum of those already-rounded per-line charges."

        Design: Corner/calculations/count_mismatch_outranks_quantity_significance_across_lines
        """
        set_clock()
        facility, _instrument = create_funded_facility()
        generator = create_generator()
        drummed = create_approved_profile(
            generator["id"], facility["id"], profile_overrides={"physical_form": "SOLID"}
        )
        bulk = create_approved_profile(
            generator["id"], facility["id"], profile_overrides={"physical_form": "BULK_LIQUID"}
        )
        manifest = create_manifest(
            generator["id"],
            facility["id"],
            lines=[
                manifest_line_payload(drummed["id"], 1000.0, 4, False),
                manifest_line_payload(bulk["id"], 1000.0, 0, True),
            ],
        )

        response = api_client.receive_manifest(
            manifest["id"],
            receive_payload(
                [receipt_line(1, 1000.0, 3), receipt_line(2, 900.0, 0)]
            ),
            TEST_USERS["clerk"],
        )
        received = validate_success(response)

        assert received["status"] == "DISCREPANT"
        assert received["discrepancy_type"] == "COUNT_MISMATCH"
        assert received["arrived_at"].startswith("2026-08-01T00:00:00")
        # The exception-report window opens 15 days after arrival and nothing is filed yet.
        assert received["discrepancy_report_due_at"].startswith("2026-08-16T00:00:00")
        assert received["discrepancy_report_filed"] is False

        # Line one: a SOLID base rate of 30 cents per kilogram times the 1.20
        # ORGANIC_SOLVENT hazard multiplier, no land-disposal surcharge, priced on the
        # weighed 1000.0 kg, plus 750 cents for each of the three received containers.
        solid_rate = Decimal("30") * Decimal("1.20")
        line1_expected = (
            _round_half_up_cents(Decimal("1000.0") * solid_rate) + 750 * 3
        )
        # Line two: a BULK_LIQUID base rate of 40 cents times the same 1.20
        # multiplier, priced on the weighed 900.0 kg, with no containers to handle.
        bulk_rate = Decimal("40") * Decimal("1.20")
        line2_expected = _round_half_up_cents(Decimal("900.0") * bulk_rate) + 750 * 0
        assert_cents(received["provisional_charge_cents"], line1_expected + line2_expected)

        line1, line2 = read_lines(manifest["id"])
        assert line1["significance"] == "COUNT_MISMATCH"
        # Weighed exactly as declared, so the variance is zero and the mismatch is
        # entirely about the drum count.
        assert_ratio(line1["variance_pct"], 0.0, "variance_pct")
        assert line1["line_status"] == "RECEIVED"
        assert_mass(line1["accepted_quantity_kg"], 1000.0, "accepted_quantity_kg")
        assert_cents(line1["provisional_line_charge_cents"], line1_expected)

        assert line2["significance"] == "QUANTITY_SIGNIFICANT"
        # (1000.0 - 900.0) / 1000.0 reaches the bulk tolerance of 0.10 exactly.
        assert_ratio(line2["variance_pct"], 0.1, "variance_pct")
        assert_mass(line2["accepted_quantity_kg"], 900.0, "accepted_quantity_kg")
        assert_cents(line2["provisional_line_charge_cents"], line2_expected)

        offeror = read_generator(generator["id"])
        assert_cents(offeror["open_charge_cents"], line1_expected + line2_expected)
        assert_cents(offeror["settled_charge_cents"], 0)


class TestGeneratorReliabilityInputs:
    def test_reliability_counts_only_closed_manifests(self):
        """One certified manifest, one still-discrepant manifest and one failed
        characterisation: both score variants must read the value that ignores the
        discrepant shipment entirely, since only closed manifests are in the set.

        "Both use the same weighted formula and differ only in which closed manifests they consider; a manifest is closed when its `status` is `CERTIFIED` or `REJECTED_RETURNED`."

        "The profile failure rate is computed identically in both variants and is not windowed at all: it is the count of the generator's waste profiles whose `status` is `SAMPLE_FAILED` or `REJECTED`, divided by the count of the generator's waste profiles whose `status` is anything other than `DRAFT`, and it is taken as zero when that denominator is zero."

        "The score is then 100, less 45 times the discrepancy rate, less 35 times the return rate, less 20 times the profile failure rate; the result is rounded half up to a whole number and then clamped into the inclusive range from 0 to 100."

        Design: Corner/calculations/reliability_score_excludes_manifests_that_are_not_closed
        """
        set_clock()
        facility, _instrument = create_funded_facility()
        generator = create_generator()
        approved = create_approved_profile(generator["id"], facility["id"])

        clean = create_manifest(
            generator["id"],
            facility["id"],
            lines=[manifest_line_payload(approved["id"], 1000.0, 4, False)],
        )
        receive_manifest(clean["id"], [receipt_line(1, 1000.0, 4)])
        certified = certify_manifest(clean["id"])
        assert certified["status"] == "CERTIFIED"
        assert certified["discrepancy_type"] == "NONE"

        # A second characterisation fails its verification: 15000.0 against a declared
        # 12000.0 ppm is a deviation of 0.2500, beyond the 0.15 FINGERPRINT allowance.
        failing = create_draft_profile(
            generator["id"], facility["id"], waste_codes=["F003"]
        )
        submit_profile(failing["id"], generator["id"])
        record_sample(failing["id"], measured_constituent_ppm=15000.0)
        assert read_profile(failing["id"])["status"] == "SAMPLE_FAILED"

        short = create_manifest(
            generator["id"],
            facility["id"],
            manifest_tracking_number="MTN0000002",
            lines=[manifest_line_payload(approved["id"], 1000.0, 4, False)],
        )
        discrepant = receive_manifest(short["id"], [receipt_line(1, 800.0, 4)])
        assert discrepant["status"] == "DISCREPANT"
        assert discrepant["discrepancy_type"] == "QUANTITY_SIGNIFICANT"

        response = api_client.get_reliability_score(
            generator["id"], TEST_USERS["compliance_manager"]
        )
        scores = validate_success(response)

        # The set is the single CERTIFIED manifest: no discrepancy and no return in
        # it, so both those rates are zero. One of the generator's two non-draft
        # profiles failed its sample, so the profile failure rate is 1/2.
        expected = int(
            (Decimal(100) - Decimal(45) * 0 - Decimal(35) * 0 - Decimal(20) * Decimal("0.5")).quantize(
                CENT, rounding=ROUND_HALF_UP
            )
        )
        assert expected == 90
        assert scores["reliability_score_rolling"] == expected
        assert scores["reliability_score_lifetime"] == expected
        # Counting the discrepant shipment would have produced 68 instead.
        wrongly_included = int(
            (
                Decimal(100)
                - Decimal(45) * Decimal("0.5")
                - Decimal(20) * Decimal("0.5")
            ).quantize(CENT, rounding=ROUND_HALF_UP)
        )
        assert scores["reliability_score_rolling"] != wrongly_included
        assert scores["reliability_score_lifetime"] != wrongly_included
        assert read_generator(generator["id"])["status"] == "ACTIVE"


class TestBiennialReportScope:
    def test_report_year_follows_arrival_not_creation_order(self):
        """Two shipments arrive an hour and a half apart across the year boundary,
        the later-arriving one having been created first. Each report year must
        contain exactly the arrival that falls inside it.

        "In scope are the facility's manifests whose `arrived_at` is not null and whose `arrived_at` falls within the calendar year `report_year` in UTC, ordered by `arrived_at` ascending with `created_at` ascending as the tie-break, so manifests created out of chronological order still report in arrival order."

        "A manifest still `EN_ROUTE`, having no `arrived_at`, is excluded no matter what its `shipped_on` says; a manifest that arrived on 31 December of the report year is included, and one that arrived on 1 January of the following year is not."

        Design: Corner/calculations/biennial_report_scopes_by_arrival_year_not_creation_order
        """
        set_clock()
        facility, _instrument = create_funded_facility()
        generator = create_generator()
        profile = create_approved_profile(
            generator["id"], facility["id"], profile_overrides={"waste_codes": ["D001"]}
        )

        set_clock("2026-12-31T23:00:00Z")
        # The shipment that will arrive in the new year is created first.
        next_year = create_manifest(
            generator["id"],
            facility["id"],
            manifest_tracking_number="MTN0000002",
            shipped_on="2026-12-30",
            lines=[manifest_line_payload(profile["id"], 700.0, 2, False)],
        )
        this_year = create_manifest(
            generator["id"],
            facility["id"],
            manifest_tracking_number="MTN0000001",
            shipped_on="2026-12-30",
            lines=[manifest_line_payload(profile["id"], 500.0, 2, False)],
        )
        receive_manifest(this_year["id"], [receipt_line(1, 500.0, 2)])
        set_clock("2027-01-01T00:30:00Z")
        receive_manifest(next_year["id"], [receipt_line(1, 700.0, 2)])

        assert read_manifest(this_year["id"])["arrived_at"].startswith("2026-12-31T23:00:00")
        assert read_manifest(next_year["id"])["arrived_at"].startswith("2027-01-01T00:30:00")

        report_2026 = validate_success(
            api_client.get_biennial_report(
                facility["id"], TEST_USERS["inspector"], params={"report_year": 2026}
            )
        )
        assert report_2026["report_year"] == 2026
        assert report_2026["manifest_count"] == 1
        assert report_2026["generator_count"] == 1
        assert_mass(report_2026["total_received_kg"], 500.0, "total_received_kg")
        assert_mass(report_2026["total_accepted_kg"], 500.0, "total_accepted_kg")
        assert_mass(report_2026["total_returned_kg"], 0.0, "total_returned_kg")
        assert_mass(report_2026["total_residue_kg"], 0.0, "total_residue_kg")
        assert sorted(report_2026["waste_code_totals"]) == ["D001"]
        assert_mass(report_2026["waste_code_totals"]["D001"], 500.0, "D001 received")

        report_2027 = validate_success(
            api_client.get_biennial_report(
                facility["id"], TEST_USERS["inspector"], params={"report_year": 2027}
            )
        )
        assert report_2027["manifest_count"] == 1
        assert_mass(report_2027["total_received_kg"], 700.0, "total_received_kg")
        assert_mass(report_2027["waste_code_totals"]["D001"], 700.0, "D001 received")

        # Both shipments are on the facility's intake side of the ledger.
        assert_mass(read_facility(facility["id"])["received_mass_kg"], 1200.0, "received_mass_kg")


class TestCompatibilitySegregation:
    def test_both_segregation_clauses_refuse_a_water_reactive_drum(self):
        """A water-reactive drum is refused by an empty unit that never authorised
        the class, and refused again by a unit that authorises it but already holds
        an acid drum; a second acid drum joins the first without objection.

        "First, the container's compatibility class — taken from its profile — must appear in the target unit's `allowed_compatibility_classes`."

        "This clause is checked first, so a class the permit never authorised for that unit is refused even when the unit is completely empty."

        "Second, for every resident container in the unit whose custody is neither `VOIDED` nor `EMPTIED`, the pair formed by the candidate's class and the resident's class must not be one of the six incompatible pairs: acid with alkaline, acid with cyanide-bearing, acid with water-reactive, oxidizer with organic solvent, oxidizer with water-reactive, and water-reactive with alkaline."

        "The table is symmetric, and no class is incompatible with itself, so two drums of the same class always co-locate."

        "Violation of either clause is `ERR_INCOMPATIBLE_SEGREGATION`."

        Design: Corner/calculations/incompatible_class_placement_rejected_on_both_clauses
        """
        set_clock()
        facility, _instrument = create_funded_facility()
        generator = create_generator()
        solvent_and_acid_unit = create_storage_unit(
            facility["id"],
            unit_code="CA-01",
            allowed_compatibility_classes=["ORGANIC_SOLVENT", "ACID"],
        )
        acid_and_reactive_unit = create_storage_unit(
            facility["id"],
            unit_code="CA-02",
            allowed_compatibility_classes=["ACID", "WATER_REACTIVE"],
        )
        acid_profile = create_approved_profile(
            generator["id"],
            facility["id"],
            profile_overrides={
                "waste_codes": ["D002"],
                "compatibility_class": "ACID",
                "declared_ph": 2.0,
                "requested_treatment_method": "NEUTRALIZATION",
            },
            sample_overrides={"measured_ph": 2.2},
            approved_treatment_method="NEUTRALIZATION",
        )
        reactive_profile = create_approved_profile(
            generator["id"],
            facility["id"],
            profile_overrides={
                "waste_codes": ["D003"],
                "compatibility_class": "WATER_REACTIVE",
                "declared_ph": 9.0,
                "requested_treatment_method": "NEUTRALIZATION",
            },
            sample_overrides={"measured_ph": 9.2},
            approved_treatment_method="NEUTRALIZATION",
        )
        manifest = create_manifest(
            generator["id"],
            facility["id"],
            lines=[
                manifest_line_payload(acid_profile["id"], 1000.0, 4, False),
                manifest_line_payload(reactive_profile["id"], 1000.0, 4, False),
            ],
        )
        receive_manifest(
            manifest["id"], [receipt_line(1, 1000.0, 4), receipt_line(2, 1000.0, 4)]
        )
        acid_line, reactive_line = read_lines(manifest["id"])
        place_container(
            acid_line["id"],
            acid_and_reactive_unit["id"],
            net_weight_kg=200.0,
            label_waste_codes=["D002"],
            label_hazard_class="8",
        )

        # First clause: the class is simply not on this unit's permit, and the unit
        # holds nothing at all.
        first_clause = api_client.create_container(
            container_payload(
                reactive_line["id"],
                solvent_and_acid_unit["id"],
                net_weight_kg=200.0,
                label_waste_codes=["D003"],
                label_hazard_class="4.3",
            ),
            TEST_USERS["clerk"],
        )
        validate_error(first_clause, "ERR_INCOMPATIBLE_SEGREGATION")

        # Second clause: the class is authorised here, but acid with water-reactive
        # is one of the six incompatible pairs and an acid drum is resident.
        second_clause = api_client.create_container(
            container_payload(
                reactive_line["id"],
                acid_and_reactive_unit["id"],
                net_weight_kg=200.0,
                label_waste_codes=["D003"],
                label_hazard_class="4.3",
            ),
            TEST_USERS["clerk"],
        )
        validate_error(second_clause, "ERR_INCOMPATIBLE_SEGREGATION")

        # No class is incompatible with itself, so a second acid drum co-locates.
        same_class = api_client.create_container(
            container_payload(
                acid_line["id"],
                acid_and_reactive_unit["id"],
                net_weight_kg=150.0,
                label_waste_codes=["D002"],
                label_hazard_class="8",
            ),
            TEST_USERS["clerk"],
        )
        validate_success(same_class, expected_status=201)

        assert_unit_state(
            read_unit(solvent_and_acid_unit["id"]), container_count=0, stored_kg=0.0
        )
        assert_unit_state(
            read_unit(acid_and_reactive_unit["id"]), container_count=2, stored_kg=350.0
        )
        # Nothing was ever drawn from the water-reactive receipt line.
        _acid_line_after, reactive_line_after = read_lines(manifest["id"])
        assert_mass(
            reactive_line_after["allocated_container_mass_kg"],
            0.0,
            "allocated_container_mass_kg",
        )


class TestCorrectiveActionProjection:
    def test_projection_and_reserve_read_different_finding_status_sets(self):
        """A single significant-non-complier finding walks the whole cycle: the
        projection moves NONE, OPEN, IN_PROGRESS, COMPLETED and back to OPEN, while
        the reserve is held right through the responded stage and only released on
        closure.

        "`corrective_action_status` is `NONE` when the facility has no findings at all, otherwise `OPEN` when any finding is `OPEN` or `REOPENED`, otherwise `IN_PROGRESS` when any finding is `RESPONDED`, and otherwise `COMPLETED` — that last case meaning every finding is `CLOSED`."

        "Crucially, neither path changes `open_snc_finding_count` or `corrective_action_reserve_cents`: because the count includes `RESPONDED`, an `SNC` reserve is held until the regulator actually closes the finding."

        "A `RegulatoryInspector` may reopen a `CLOSED` finding by naming a `to_status` of `REOPENED`, which is permitted only while `reopen_count` is no greater than 2 and is otherwise an invalid state; reopening increments `reopen_count`, resets `corrective_action_due_at` to 30 days after the current clock instant, and — for an `SNC` finding — raises `open_snc_finding_count` and `corrective_action_reserve_cents` by 5,000,000 cents again."

        Design: Corner/calculations/corrective_action_projection_tracks_finding_status_and_reserve
        """
        set_clock()
        facility, _instrument = create_funded_facility(face_amount_cents=90_000_000)
        post_closure = facility["post_closure_cost_cents"]

        _base, tier, estimate, no_reserve, required_clean = _assurance_figures(
            "0", post_closure, 0
        )
        _base, _tier, _estimate, one_reserve, required_cited = _assurance_figures(
            "0", post_closure, 1
        )

        empty = read_facility(facility["id"])
        assert empty["corrective_action_status"] == "NONE"
        assert empty["assurance_tier"] == tier
        assert_cents(empty["closure_cost_estimate_cents"], estimate)
        assert_cents(empty["corrective_action_reserve_cents"], no_reserve)
        assert_cents(empty["required_assurance_cents"], required_clean)
        assert_cents(empty["assurance_shortfall_cents"], 0)

        cited = validate_success(
            api_client.create_compliance_finding(
                finding_payload(
                    facility["id"],
                    finding_class="SNC",
                    citation_code="40CFR264.15",
                    corrective_action_due_at="2026-09-30T00:00:00Z",
                    is_prior_release=True,
                ),
                TEST_USERS["inspector"],
            ),
            expected_status=201,
        )
        assert cited["status"] == "OPEN"
        assert cited["is_prior_release"] is True
        assert cited["reopen_count"] == 0
        after_citation = read_facility(facility["id"])
        assert after_citation["corrective_action_status"] == "OPEN"
        assert after_citation["open_snc_finding_count"] == 1
        assert_cents(after_citation["corrective_action_reserve_cents"], one_reserve)
        assert_cents(after_citation["required_assurance_cents"], required_cited)

        validate_success(
            api_client.set_compliance_finding_status(
                cited["id"],
                finding_status_payload(
                    "RESPONDED",
                    corrective_action_completed_on="2026-08-01",
                    reason_code="RELEASE_REMEDIATED",
                ),
                TEST_USERS["compliance_manager"],
            )
        )
        responded = read_facility(facility["id"])
        assert responded["corrective_action_status"] == "IN_PROGRESS"
        assert responded["open_snc_finding_count"] == 1
        assert_cents(responded["corrective_action_reserve_cents"], one_reserve)
        assert_cents(responded["required_assurance_cents"], required_cited)

        validate_success(
            api_client.set_compliance_finding_status(
                cited["id"], finding_status_payload("CLOSED"), TEST_USERS["inspector"]
            )
        )
        closed = read_facility(facility["id"])
        assert closed["corrective_action_status"] == "COMPLETED"
        assert closed["open_snc_finding_count"] == 0
        assert_cents(closed["corrective_action_reserve_cents"], no_reserve)
        assert_cents(closed["required_assurance_cents"], required_clean)

        reopened_finding = validate_success(
            api_client.set_compliance_finding_status(
                cited["id"],
                finding_status_payload("REOPENED", reason_code="RELEASE_RECURRED"),
                TEST_USERS["inspector"],
            )
        )
        assert reopened_finding["reopen_count"] == 1
        # Thirty days after the clock instant of the reopening.
        assert reopened_finding["corrective_action_due_at"].startswith("2026-08-31T00:00:00")
        reopened = read_facility(facility["id"])
        assert reopened["corrective_action_status"] == "OPEN"
        assert reopened["open_snc_finding_count"] == 1
        assert_cents(reopened["corrective_action_reserve_cents"], one_reserve)
        assert_cents(reopened["required_assurance_cents"], required_cited)
        # The posted instrument covers every figure above, so nothing is ever short.
        assert_cents(reopened["assurance_shortfall_cents"], 0)
