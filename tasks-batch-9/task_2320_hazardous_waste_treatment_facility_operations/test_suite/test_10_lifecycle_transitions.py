"""Lifecycle transitions of the hazardous waste TSDF API.

Each test walks one documented state machine across a single edge — a defined
transition and the rows it touches, an undefined one and the refusal it earns,
or a compensating one and the figures it hands back. Every precondition is built
through the documented endpoints against the logical clock, which starts at
2026-08-01T00:00:00Z and moves only when a test moves it.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_cents,
    assert_mass,
    factories,
    fixtures,
    make_generator_headers,
)


class TestTreatmentBatchLifecycle:
    """Scheduling freezes a batch's arithmetic; aborting hands it all back."""

    def test_batch_creation_freezes_input_figures_at_planned(self):
        """Scheduling a run over one sealed 200.0 kg drum opens the batch in
        PLANNED with its three frozen figures and its empty residue record.

        "Three figures are frozen at creation and never recomputed thereafter: `input_mass_kg`, the sum of `net_weight_kg` across the staged containers to 3 decimals; `dominant_compatibility_class`, the compatibility class of the staged container with the greatest `net_weight_kg`, with the lowest container `created_at` breaking a tie; and `estimated_treatment_liability_cents`, `input_mass_kg` multiplied by 220 cents per kilogram and rounded half up to whole cents."
        "A new batch opens `PLANNED`, with `residue_constituent_ppm`, `residue_flash_point_c` and `verification_sample_ppm` null, `residue_mass_kg` zero, `ldr_standard_ppm` null, `ldr_result` of `PENDING`, `completed_by_user_id` and `verified_by_user_id` null, `retreat_count` zero and `held_reason_code` of `NONE`."
        "Creation stages each listed container, raises the unit's `reserved_kg` by the frozen input mass, and raises the facility's `active_treatment_liability_cents` and `required_assurance_cents` by the frozen liability."

        Design: Corner/state_machines/treatment_batch_creation_freezes_input_figures_at_planned
        """
        scenario = fixtures.setup_sealed_container(net_weight_kg=200.0)

        response = api_client.create_treatment_batch(
            factories.treatment_batch_payload(
                scenario.facility["id"],
                scenario.unit["id"],
                [scenario.container["id"]],
                treatment_method="INCINERATION",
                window_start="2026-08-01T00:00:00Z",
                window_end="2026-08-01T12:00:00Z",
            ),
            TEST_USERS["operator"],
        )
        batch = validate_success(response, expected_status=201)

        assert batch["status"] == "PLANNED"
        assert_mass(batch["input_mass_kg"], 200.0, "input_mass_kg")
        assert batch["dominant_compatibility_class"] == "ORGANIC_SOLVENT"
        # 200.0 kg at 220 cents per kilogram.
        assert_cents(
            batch["estimated_treatment_liability_cents"],
            44_000,
            "estimated_treatment_liability_cents",
        )
        assert batch["ldr_result"] == "PENDING"
        assert batch["ldr_standard_ppm"] is None
        assert batch["retreat_count"] == 0
        assert batch["held_reason_code"] == "NONE"
        assert_mass(batch["residue_mass_kg"], 0.0, "residue_mass_kg")
        assert batch["residue_constituent_ppm"] is None
        assert batch["completed_by_user_id"] is None
        assert batch["verified_by_user_id"] is None

        staged = fixtures.read_container(scenario.container["id"])
        assert staged["custody_state"] == "STAGED"
        assert staged["treatment_batch_id"] == batch["id"]

        unit = fixtures.read_unit(scenario.unit["id"])
        assert_mass(unit["reserved_kg"], 200.0, "reserved_kg")

    def test_abort_returns_containers_and_releases_reserved_mass(self):
        """Aborting a planned run unstages its drum and gives the unit's
        reserved mass and the facility's treatment liability back exactly.

        "`ABORT` moves the batch to the terminal `ABORTED` and is defined from three source statuses — `PLANNED`, `HELD` and `IN_TREATMENT` — with identical effects in all three: every staged container returns to `SEALED` with `treatment_batch_id` cleared to null, and the batch leaves the unit's `reserved_kg` and the facility's `active_treatment_liability_cents`, so the facility's `required_assurance_cents` returns exactly to its pre-creation value with no rounding drift."

        Design: Corner/state_machines/batch_abort_returns_containers_and_releases_reserved_mass
        """
        scenario = fixtures.setup_planned_batch()

        # While the run stands: 200.0 kg reserved and 44,000 cents of liability
        # on top of the 34,628,000-cent requirement of 200.0 kg held.
        assert_mass(scenario.unit["reserved_kg"], 200.0, "reserved_kg")
        assert_cents(
            scenario.facility["active_treatment_liability_cents"],
            44_000,
            "active_treatment_liability_cents",
        )
        assert_cents(
            scenario.facility["required_assurance_cents"],
            34_672_000,
            "required_assurance_cents",
        )

        response = api_client.batch_operation(
            scenario.batch["id"],
            factories.batch_operation_payload("ABORT"),
            TEST_USERS["operator"],
        )
        aborted = validate_success(response, expected_status=200)
        assert aborted["status"] == "ABORTED"

        container = fixtures.read_container(scenario.container["id"])
        assert container["custody_state"] == "SEALED"
        assert container["treatment_batch_id"] is None

        unit = fixtures.read_unit(scenario.unit["id"])
        assert_mass(unit["reserved_kg"], 0.0, "reserved_kg")
        assert_mass(unit["stored_kg"], 200.0, "stored_kg")

        facility = fixtures.read_facility(scenario.facility["id"])
        assert_cents(
            facility["active_treatment_liability_cents"],
            0,
            "active_treatment_liability_cents",
        )
        assert_mass(facility["held_mass_kg"], 200.0, "held_mass_kg")
        assert_cents(
            facility["required_assurance_cents"], 34_628_000, "required_assurance_cents"
        )
        assert_cents(facility["assurance_shortfall_cents"], 0, "assurance_shortfall_cents")


class TestWasteProfileSubmission:
    """Submission is an edge of the profile machine, not an upsert."""

    def test_submit_from_approved_is_not_a_defined_transition(self):
        """An approved characterisation cannot be re-submitted for laboratory
        work, and the refusal leaves its approval record exactly as signed.

        "Submission is defined from three source statuses."
        "On approval the profile moves to `APPROVED`, `approved_at` is stamped from the clock, `approved_by_user_id` records the signing chemist, `approved_treatment_method` is locked in from the body, and `recertification_due_at` is set to `approved_at` advanced by `recertification_months` calendar months."
        "**State.** The target entity is in a state from which the requested transition or write is defined, including terminal-state lockdown, the retreat ceiling of at most one prior re-treatment, the reopen ceiling of at most two prior reopenings, and the requirement that a unit hold no containers before it may close — `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/waste_profile_submit_from_approved_rejected
        """
        fixtures.set_clock()
        facility = fixtures.create_facility()
        generator = fixtures.create_generator()
        profile = fixtures.create_approved_profile(generator["id"], facility["id"])
        assert profile["status"] == "APPROVED"

        response = api_client.submit_waste_profile(
            profile["id"], make_generator_headers(generator["id"])
        )
        validate_error(response, "ERR_INVALID_STATE")

        after = fixtures.read_profile(profile["id"])
        assert after["status"] == "APPROVED"
        assert after["sample_attempt_count"] == 1
        assert after["approved_treatment_method"] == "INCINERATION"
        assert after["approved_at"].startswith("2026-08-01T00:00:00")

    def test_replaying_submit_on_a_submitted_profile_is_refused(self):
        """A second submission of a profile already awaiting the laboratory is
        refused rather than silently re-deriving the sample requirement.

        "Submission is defined from three source statuses."
        "That recomputation is a single threshold: `required_sample_type` becomes `FULL` when the generator's rolling reliability score is below 60, or when the profile's `sample_attempt_count` is at least 1; otherwise it becomes `FINGERPRINT`."
        "Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp in the same format that is refreshed whenever any stored or derived property of the row changes, and `version`, an integer that starts at 1 on creation and increments by one on every mutation of the row."

        Design: Corner/state_machines/repeated_profile_submit_is_not_idempotent_and_rejected
        """
        fixtures.set_clock()
        facility = fixtures.create_facility()
        generator = fixtures.create_generator()
        profile = fixtures.create_draft_profile(generator["id"], facility["id"])
        submitted = fixtures.submit_profile(profile["id"], generator["id"])
        assert submitted["status"] == "SUBMITTED"

        response = api_client.submit_waste_profile(
            profile["id"], make_generator_headers(generator["id"])
        )
        validate_error(response, "ERR_INVALID_STATE")

        after = fixtures.read_profile(profile["id"])
        assert after["status"] == "SUBMITTED"
        # A brand-new generator reads 100 on the rolling variant and the
        # profile has never been sampled, so the fingerprint requirement holds.
        assert after["required_sample_type"] == "FINGERPRINT"
        assert after["sample_attempt_count"] == 0
        assert after["version"] == submitted["version"]


class TestManifestLifecycle:
    """Certification is reachable only from a verified shipment."""

    def test_certification_before_receipt_is_refused(self):
        """A shipment still on the road cannot be certified, so no charge is
        settled against the offering generator and no mass is booked in.

        "It moves the manifest from `VERIFIED` to the terminal `CERTIFIED` and requires either that `discrepancy_type` be `NONE` or that `discrepancy_report_filed` already be true; otherwise it is refused with `ERR_DISCREPANCY_REPORT_OVERDUE`."
        "Every line opens with `line_status` of `DECLARED`, with `received_quantity_kg`, `received_container_count`, `accepted_quantity_kg` and `returned_quantity_kg` all at zero, and the manifest itself opens `EN_ROUTE` with `arrived_at` null, `discrepancy_type` of `NONE`, `resolution_type` of `NONE`, `discrepancy_report_filed` false, and `discrepancy_report_due_at`, `discrepancy_resolved_at` and `final_charge_cents` all null."
        "`received_mass_kg` is the sum of `received_quantity_kg` over the lines of the facility's manifests whose `status` is `DISCREPANT`, `VERIFIED`, `CERTIFIED` or `REJECTED_RETURNED`."

        Design: Corner/state_machines/manifest_certification_before_receipt_rejected
        """
        fixtures.set_clock()
        facility, _instrument = fixtures.create_funded_facility()
        generator = fixtures.create_generator()
        profile = fixtures.create_approved_profile(generator["id"], facility["id"])
        manifest = fixtures.create_manifest(
            generator["id"],
            facility["id"],
            lines=[factories.manifest_line_payload(profile["id"], 1000.0, 4, False)],
        )
        assert manifest["status"] == "EN_ROUTE"

        response = api_client.certify_manifest(
            manifest["id"], factories.certify_payload(), TEST_USERS["clerk"]
        )
        validate_error(response, "ERR_INVALID_STATE")

        after = fixtures.read_manifest(manifest["id"])
        assert after["status"] == "EN_ROUTE"
        assert after["arrived_at"] is None
        assert after["final_charge_cents"] is None

        assert_cents(
            fixtures.read_generator(generator["id"])["settled_charge_cents"],
            0,
            "settled_charge_cents",
        )
        assert_mass(
            fixtures.read_facility(facility["id"])["received_mass_kg"],
            0.0,
            "received_mass_kg",
        )


class TestFacilityPermitLifecycle:
    """Termination is terminal, and it drags the units along with it."""

    def test_grant_after_termination_is_refused(self):
        """Once the regulator terminates an expired permit, no later grant can
        resurrect the facility or move its permit term.

        "`TERMINATED` is terminal; no further permit transition is defined out of it."
        "**State.** The target entity is in a state from which the requested transition or write is defined, including terminal-state lockdown, the retreat ceiling of at most one prior re-treatment, the reopen ceiling of at most two prior reopenings, and the requirement that a unit hold no containers before it may close — `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/permit_decision_on_terminated_facility_rejected
        """
        fixtures.set_clock()
        facility = fixtures.create_facility(permit_expires_at="2026-08-15T00:00:00Z")
        # Past the permit term, so the facility is observed as expired.
        fixtures.set_clock("2026-08-16T00:00:00Z")

        terminated = validate_success(
            api_client.decide_permit(
                facility["id"],
                factories.permit_decision_payload("TERMINATE"),
                TEST_USERS["inspector"],
            ),
            expected_status=200,
        )
        assert terminated["permit_status"] == "TERMINATED"

        response = api_client.decide_permit(
            facility["id"],
            factories.permit_decision_payload(
                "GRANT", new_permit_expires_at="2027-12-31T00:00:00Z"
            ),
            TEST_USERS["inspector"],
        )
        validate_error(response, "ERR_INVALID_STATE")

        after = fixtures.read_facility(facility["id"])
        assert after["permit_status"] == "TERMINATED"
        assert after["permit_expires_at"].startswith("2026-08-15T00:00:00")

    def test_termination_drags_active_units_into_closing(self):
        """Termination moves every active storage unit to closing with the
        stipulated closure reference, and the derived posture follows.

        "A `TERMINATE` moves an `EXPIRED` facility to the terminal `TERMINATED` status and, as a cascade, moves every `ACTIVE` storage unit of that facility to `CLOSING` with its `closure_plan_ref` set to the literal string `PERMIT_TERMINATION`."
        "The unit's `posture` is `CLOSED` when its `status` is `CLOSING` or `CLOSED`."

        Design: Corner/state_machines/permit_termination_cascades_active_units_into_closing
        """
        fixtures.set_clock()
        facility = fixtures.create_facility(permit_expires_at="2026-08-15T00:00:00Z")
        unit = fixtures.create_storage_unit(facility["id"])
        assert unit["status"] == "ACTIVE"
        fixtures.set_clock("2026-08-16T00:00:00Z")

        response = api_client.decide_permit(
            facility["id"],
            factories.permit_decision_payload("TERMINATE"),
            TEST_USERS["inspector"],
        )
        facility_after = validate_success(response, expected_status=200)
        assert facility_after["permit_status"] == "TERMINATED"

        unit_after = fixtures.read_unit(unit["id"])
        assert unit_after["status"] == "CLOSING"
        assert unit_after["posture"] == "CLOSED"
        assert unit_after["closure_plan_ref"] == "PERMIT_TERMINATION"
        assert unit_after["container_count"] == 0


class TestContainerLifecycle:
    """Custody moves are guarded by labelling; condition recovery by repairs."""

    def test_sealing_without_the_accumulation_start_mark_is_refused(self):
        """A drum may be placed without its accumulation start date marked, but
        it may not be sealed until the mark is there.

        "Sealing a container advances it from `FILLING` to `SEALED` and is permitted only when `label_accumulation_start_marked` is true, failing which the request is refused with `ERR_LABEL_INCOMPLETE`; the move leaves `compliance_state` untouched, because the dimensions are independent."
        "Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp in the same format that is refreshed whenever any stored or derived property of the row changes, and `version`, an integer that starts at 1 on creation and increments by one on every mutation of the row."

        Design: Corner/state_machines/container_seal_without_accumulation_start_mark_rejected
        """
        scenario = fixtures.setup_received_manifest()

        placed = validate_success(
            api_client.create_container(
                factories.container_payload(
                    scenario.line["id"],
                    scenario.unit["id"],
                    net_weight_kg=200.0,
                    label_accumulation_start_marked=False,
                ),
                TEST_USERS["clerk"],
            ),
            expected_status=201,
        )
        assert placed["custody_state"] == "FILLING"
        assert placed["label_accumulation_start_marked"] is False

        response = api_client.set_container_custody_state(
            placed["id"], factories.custody_payload("SEALED"), TEST_USERS["clerk"]
        )
        validate_error(response, "ERR_LABEL_INCOMPLETE")

        after = fixtures.read_container(placed["id"])
        assert after["custody_state"] == "FILLING"
        assert after["compliance_state"] == "COMPLIANT"
        assert after["version"] == 1

    def test_condemned_drum_cannot_recover_while_its_repair_order_stands(self):
        """A leak citation condemns the drum and opens a repair order; the drum
        cannot be declared sound again until that order is repaired.

        "Recovering from `CONDEMNED` to `COMPLIANT` is permitted only when no emission repair order for that container remains in any status other than `REPAIRED`; otherwise it is an invalid state."
        "`leak_detected` is true when `measured_organic_vapor_ppm` reaches or exceeds the leak definition of the unit's `air_emission_control_level`, or when `finding_code` is `CONTAINER_LEAK` or `TANK_SHELL_CORROSION`."

        Design: Corner/state_machines/condemned_container_recovery_with_open_repair_order_rejected
        """
        scenario = fixtures.setup_container_in_storage()

        inspection = fixtures.condemn_container_by_inspection(
            scenario.unit["id"], scenario.container["id"]
        )
        assert inspection["leak_detected"] is True

        condemned = fixtures.read_container(scenario.container["id"])
        assert condemned["compliance_state"] == "CONDEMNED"
        assert condemned["last_finding_code"] == "CONTAINER_LEAK"

        response = api_client.set_container_compliance_state(
            scenario.container["id"],
            factories.compliance_payload("COMPLIANT"),
            TEST_USERS["compliance_manager"],
        )
        validate_error(response, "ERR_INVALID_STATE")

        assert (
            fixtures.read_container(scenario.container["id"])["compliance_state"]
            == "CONDEMNED"
        )

        orders, meta = validate_paginated(
            api_client.list_repair_orders(
                TEST_USERS["compliance_manager"],
                params={"storage_unit_id": scenario.unit["id"]},
            )
        )
        assert meta["total_count"] == 1
        assert orders[0]["status"] == "OPEN"

        assert fixtures.read_unit(scenario.unit["id"])["posture"] == "SUSPENDED"


class TestStorageUnitClosure:
    """A unit may enter closure holding waste but not be declared closed."""

    def test_closing_unit_holding_a_drum_cannot_be_declared_closed(self):
        """The last drum has to leave before the closure certificate is
        allowed, and the refused attempt leaves the unit closing.

        "Moving from `CLOSING` to the terminal `CLOSED` carries three preconditions, each an invalid state when violated: `container_count` must be zero; no batch on the unit may be `PLANNED`, `HELD`, `IN_TREATMENT`, `TREATED` or `LDR_FAILED`; and no emission repair order on the unit may be in any status other than `REPAIRED`."
        "The unit's `posture` is `CLOSED` when its `status` is `CLOSING` or `CLOSED`."

        Design: Corner/state_machines/storage_unit_close_while_holding_containers_rejected
        """
        scenario = fixtures.setup_container_in_storage()

        closing = fixtures.set_unit_status(scenario.unit["id"], "CLOSING")
        assert closing["status"] == "CLOSING"
        assert closing["closure_plan_ref"] == "CP-CA01-2026"

        response = api_client.set_storage_unit_status(
            scenario.unit["id"],
            factories.storage_unit_status_payload("CLOSED"),
            TEST_USERS["compliance_manager"],
        )
        validate_error(response, "ERR_INVALID_STATE")

        after = fixtures.read_unit(scenario.unit["id"])
        assert after["status"] == "CLOSING"
        assert after["posture"] == "CLOSED"
        assert after["container_count"] == 1
        assert after["closure_plan_ref"] == "CP-CA01-2026"


class TestComplianceFindingCycle:
    """The finding record cycles through closure and reopening, but not forever."""

    def test_reopen_beyond_the_bounded_cycle_is_refused(self):
        """Three reopenings are allowed; the fourth attempt, with the count
        already at three, is refused and the citation stays closed.

        "A `RegulatoryInspector` may reopen a `CLOSED` finding by naming a `to_status` of `REOPENED`, which is permitted only while `reopen_count` is no greater than 2 and is otherwise an invalid state; reopening increments `reopen_count`, resets `corrective_action_due_at` to 30 days after the current clock instant, and — for an `SNC` finding — raises `open_snc_finding_count` and `corrective_action_reserve_cents` by 5,000,000 cents again."
        "`corrective_action_status` is `NONE` when the facility has no findings at all, otherwise `OPEN` when any finding is `OPEN` or `REOPENED`, otherwise `IN_PROGRESS` when any finding is `RESPONDED`, and otherwise `COMPLETED` — that last case meaning every finding is `CLOSED`."

        Design: Corner/state_machines/compliance_finding_fourth_reopen_beyond_cycle_limit_rejected
        """
        fixtures.set_clock()
        facility = fixtures.create_facility()
        finding = fixtures.file_finding(
            facility["id"],
            finding_class="MINOR",
            corrective_action_due_at="2026-09-30T00:00:00Z",
        )
        assert finding["reopen_count"] == 0

        for _cycle in range(3):
            fixtures.set_finding_status(
                finding["id"], "RESPONDED", corrective_action_completed_on="2026-08-01"
            )
            fixtures.set_finding_status(finding["id"], "CLOSED")
            reopened = fixtures.set_finding_status(finding["id"], "REOPENED")
            assert reopened["status"] == "REOPENED"

        fixtures.set_finding_status(
            finding["id"], "RESPONDED", corrective_action_completed_on="2026-08-01"
        )
        closed = fixtures.set_finding_status(finding["id"], "CLOSED")
        assert closed["status"] == "CLOSED"
        assert closed["reopen_count"] == 3

        response = api_client.set_compliance_finding_status(
            finding["id"],
            factories.finding_status_payload("REOPENED"),
            TEST_USERS["inspector"],
        )
        validate_error(response, "ERR_INVALID_STATE")

        after = fixtures.read_finding(finding["id"])
        assert after["status"] == "CLOSED"
        assert after["reopen_count"] == 3

        facility_after = fixtures.read_facility(facility["id"])
        assert facility_after["open_snc_finding_count"] == 0
        assert facility_after["corrective_action_status"] == "COMPLETED"


class TestFinancialAssuranceLifecycle:
    """Instruments supersede one another, and none may leave the facility bare."""

    def test_cancelling_the_only_covering_instrument_is_refused(self):
        """With an empty inventory the facility still owes 34,250,000 cents, so
        cancelling its sole active trust fund is refused and the row stands.

        "Cancelling an instrument moves it from `ACTIVE` to the terminal `CANCELLED`, stamps `superseded_at`, and recomputes the facility's posted figure — but cancellation is permitted only when the facility's required assurance is zero, or when another `ACTIVE` instrument covers the required amount on its own; otherwise the cancellation is refused with `ERR_FINANCIAL_ASSURANCE_SHORTFALL`."

        Design: Corner/state_machines/instrument_cancellation_leaving_requirement_uncovered_rejected
        """
        fixtures.set_clock()
        facility, instrument = fixtures.create_funded_facility(
            face_amount_cents=90_000_000
        )
        assert instrument["status"] == "ACTIVE"

        response = api_client.cancel_instrument(
            instrument["id"],
            factories.instrument_cancel_payload(),
            TEST_USERS["compliance_manager"],
        )
        validate_error(response, "ERR_FINANCIAL_ASSURANCE_SHORTFALL")

        assert fixtures.read_instrument(instrument["id"])["status"] == "ACTIVE"

        after = fixtures.read_facility(facility["id"])
        assert_cents(after["posted_assurance_cents"], 90_000_000, "posted_assurance_cents")
        # Empty inventory: 25,000,000 base at TIER_1 plus 8,000,000 post-closure.
        assert_cents(
            after["required_assurance_cents"], 34_250_000, "required_assurance_cents"
        )
        assert_cents(after["assurance_shortfall_cents"], 0, "assurance_shortfall_cents")

    def test_new_instrument_supersedes_the_prior_active_one(self):
        """A second instrument replaces rather than supplements the first, so
        the posted figure is the newcomer's face amount alone.

        "As a cascade, the facility's prior `ACTIVE` instrument moves to `SUPERSEDED`, with its `superseded_by_instrument_id` set to the new instrument's identifier and its `superseded_at` stamped with the current clock instant; the facility's `version` advances; and `posted_assurance_cents` and `assurance_shortfall_cents` are recomputed from the surviving `ACTIVE` instrument alone."

        Design: Corner/state_machines/new_instrument_supersedes_the_prior_active_instrument
        """
        fixtures.set_clock()
        facility = fixtures.create_facility()
        first = fixtures.post_instrument(
            facility["id"],
            face_amount_cents=40_000_000,
            expected_facility_version=facility["version"],
        )
        after_first = fixtures.read_facility(facility["id"])
        assert after_first["version"] == 2

        response = api_client.create_instrument(
            factories.instrument_payload(
                facility["id"],
                after_first["version"],
                face_amount_cents=50_000_000,
                instrument_type="LETTER_OF_CREDIT",
                effective_on="2026-08-01",
            ),
            TEST_USERS["compliance_manager"],
        )
        second = validate_success(response, expected_status=201)
        assert second["status"] == "ACTIVE"

        prior = fixtures.read_instrument(first["id"])
        assert prior["status"] == "SUPERSEDED"
        assert prior["superseded_by_instrument_id"] == second["id"]
        assert prior["superseded_at"].startswith("2026-08-01T00:00:00")

        after = fixtures.read_facility(facility["id"])
        assert_cents(after["posted_assurance_cents"], 50_000_000, "posted_assurance_cents")
        assert_cents(
            after["required_assurance_cents"], 34_250_000, "required_assurance_cents"
        )
        assert_cents(after["assurance_shortfall_cents"], 0, "assurance_shortfall_cents")
        assert after["version"] == 3
