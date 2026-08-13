"""Publication cycles: window semantics, posture gates, publish cascade, and
machine-readable file generation/validation."""
from test_helpers import (
    ApiErrorId,
    create_charge_record,
    create_contract,
    create_cycle,
    create_facility,
    create_payer,
    create_rate,
    create_service_item,
    freeze_cycle,
    generate_machine_file,
    get_success_data,
    publish_cycle,
    setup_frozen_cycle,
    setup_published_cycle,
    setup_validated_record,
    validate_error,
    validate_machine_file,
    validate_paginated,
    validate_record,
)
from test_helpers.factories import (
    create_charge_record_payload,
    create_cycle_payload,
    create_machine_file_payload,
)
from test_helpers.fixtures import MANAGER, OFFICER


class TestCycleWindow:
    def test_cycle_inverted_window_rejected(self, api):
        """PRD section 3.3: "Unlike contract windows, a cycle's coverage window is half-open — it includes `period_start` and excludes `period_end` — so `period_start` must fall strictly before `period_end`, otherwise creation is rejected with `ERR_INVALID_WINDOW`, and two cycles of the same facility and same `cycle_type` may not overlap unless one is terminal; windows that merely touch at an endpoint do not count as overlapping."

        Design: Corner/validations/cycle_inverted_window_rejected
        """
        fac = create_facility(name="F", cms_certification_number="CCN-H4",
                              bed_count=50)
        # period_start == period_end is an empty half-open window.
        resp = api.create_cycle(
            create_cycle_payload(
                fac["id"], period_start="2026-08-01T00:00:00Z",
                period_end="2026-08-01T00:00:00Z"),
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)

    def test_cycle_period_adjacency_allowed(self, api):
        """PRD section 3.3: "Unlike contract windows, a cycle's coverage window is half-open — it includes `period_start` and excludes `period_end` — so `period_start` must fall strictly before `period_end`, otherwise creation is rejected with `ERR_INVALID_WINDOW`, and two cycles of the same facility and same `cycle_type` may not overlap unless one is terminal; windows that merely touch at an endpoint do not count as overlapping."
        PRD section 3.3: "An overlapping create is rejected with `ERR_CYCLE_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/cycle_period_adjacency_allowed
        """
        fac = create_facility(name="F", cms_certification_number="CCN-T2",
                              bed_count=100)
        m1 = create_cycle(fac["id"])  # [2026-08-01, 2026-09-01)
        assert m1["status"] == "OPEN"
        # Adjacency at 2026-09-01 is not overlap under half-open semantics.
        m2 = create_cycle(fac["id"], period_start="2026-09-01T00:00:00Z",
                          period_end="2026-10-01T00:00:00Z")
        assert m2["status"] == "OPEN"
        # [2026-09-30, 2026-11-01) genuinely overlaps M2.
        resp = api.create_cycle(
            create_cycle_payload(fac["id"],
                                 period_start="2026-09-30T00:00:00Z",
                                 period_end="2026-11-01T00:00:00Z"),
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_CYCLE_PERIOD_OVERLAP)

    def test_cycle_period_partitioned_by_cycle_type(self, api):
        """PRD section 3.3: "Unlike contract windows, a cycle's coverage window is half-open — it includes `period_start` and excludes `period_end` — so `period_start` must fall strictly before `period_end`, otherwise creation is rejected with `ERR_INVALID_WINDOW`, and two cycles of the same facility and same `cycle_type` may not overlap unless one is terminal; windows that merely touch at an endpoint do not count as overlapping."

        Design: Difficulty/resource_temporal_overlap/cycle_period_adjacency_allowed
        """
        fac = create_facility(name="F", cms_certification_number="CCN-T2",
                              bed_count=100)
        create_cycle(fac["id"])  # MONTHLY [2026-08-01, 2026-09-01)
        create_cycle(fac["id"], period_start="2026-09-01T00:00:00Z",
                     period_end="2026-10-01T00:00:00Z")
        # The overlap rule is scoped to same facility AND same cycle_type:
        # an ANNUAL cycle containing the whole span coexists with both.
        a1 = create_cycle(fac["id"], cycle_type="ANNUAL",
                          period_start="2026-01-01T00:00:00Z",
                          period_end="2027-01-01T00:00:00Z")
        assert a1["status"] == "OPEN"


class TestPostureGates:
    def test_cycle_freeze_blocked_below_record_floor(self, api):
        """PRD section 3.4: "While the cycle is `OPEN`, its `posture` is `FREEZABLE` when `validated_record_count` has reached the facility's `min_records_per_cycle` floor, and `COLLECTING` below it."
        PRD section 3.4: "Freezing moves a cycle `OPEN → FROZEN` and is gated on posture: the attempt is rejected with `ERR_POSTURE_NOT_FREEZABLE` whenever the cycle's posture is not `FREEZABLE`, which covers both an `OPEN` cycle still below its validated-record floor and a cycle that has already left `OPEN`."

        Design: Corner/state_machines/cycle_freeze_blocked_below_record_floor
        """
        fac = create_facility(name="F", cms_certification_number="CCN-SM3",
                              bed_count=50, min_records_per_cycle=2)
        payer = create_payer(name="PA")
        contract = create_contract(fac["id"], payer["id"])
        si1 = create_service_item(fac["id"], code="70551", description="MRI",
                                  gross_charge_cents=100000)
        si2 = create_service_item(fac["id"], code="70450", description="CT",
                                  gross_charge_cents=80000)
        create_rate(contract["id"], si1["id"], rate_percent=40)
        create_rate(contract["id"], si2["id"], rate_percent=50)
        get_success_data(api.activate_contract(contract["id"], MANAGER))
        cycle = create_cycle(fac["id"])
        r1 = create_charge_record(fac["id"], cycle["id"], si1["id"],
                                  discounted_cash_cents=50000)
        r2 = create_charge_record(fac["id"], cycle["id"], si2["id"],
                                  discounted_cash_cents=40000)
        validate_record(r1["id"])
        # 1 validated record < floor 2: COLLECTING, freeze rejected.
        cycle = get_success_data(api.get_cycle(cycle["id"], OFFICER))
        assert cycle["posture"] == "COLLECTING"
        resp = api.freeze_cycle(cycle["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_POSTURE_NOT_FREEZABLE)
        # Reaching the floor flips posture to FREEZABLE and freeze succeeds.
        validate_record(r2["id"])
        cycle = get_success_data(api.get_cycle(cycle["id"], OFFICER))
        assert cycle["posture"] == "FREEZABLE"
        assert cycle["validated_record_count"] == 2
        cycle = freeze_cycle(cycle["id"])
        assert cycle["status"] == "FROZEN"

    def test_cycle_publish_blocked_without_valid_file(self, api):
        """PRD section 3.4: "Once `FROZEN`, the posture reflects the cycle's single sealed file — regeneration supersedes the prior sealed file, so at most one exists at a time: with no sealed file the posture is `AWAITING_FILE`; a sealed file whose `validation_status` is `UNVALIDATED` yields `FILE_UNVALIDATED`; `VALID` yields `PUBLISHABLE`; and `INVALID` yields `FILE_INVALID`."
        PRD section 3.4: "Publishing moves a cycle `FROZEN → PUBLISHED` and is gated on posture the same way: a posture of exactly `PUBLISHABLE` is required — precisely one `SEALED` file exists and its `validation_status` is `VALID` — and any attempt whose posture falls short, including a cycle that is not `FROZEN` at all, is rejected with `ERR_POSTURE_NOT_PUBLISHABLE`."

        Design: Corner/state_machines/cycle_publish_blocked_without_valid_file
        """
        ctx = setup_frozen_cycle(
            facility_overrides={"name": "F",
                                "cms_certification_number": "CCN-SM4",
                                "bed_count": 50})
        cycle = get_success_data(api.get_cycle(ctx["cycle"]["id"], OFFICER))
        assert cycle["posture"] == "AWAITING_FILE"
        resp = api.publish_cycle(ctx["cycle"]["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_POSTURE_NOT_PUBLISHABLE)
        cycle = get_success_data(api.get_cycle(ctx["cycle"]["id"], OFFICER))
        assert cycle["status"] == "FROZEN"


class TestPublishCascade:
    def test_cycle_supersede_cascade_on_next_publish(self, api):
        """PRD section 3.4: "The publish cascade then runs in full: the cycle's `VALIDATED` records move `VALIDATED → PUBLISHED`; the sealed file moves `SEALED → PUBLISHED` on its generation dimension; and the previously published cycle of the same facility and same `cycle_type` — selected as the one with the latest `period_start`, ties broken by `created_at` ascending — moves `PUBLISHED → SUPERSEDED`, taking its `PUBLISHED` records to `SUPERSEDED` and its `PUBLISHED` files to `SUPERSEDED` with it."
        PRD section 3.4: "The newly published cycle's posture becomes `CURRENT`, the superseded cycle's becomes `ARCHIVED`, and every mutated resource increments its `version`."

        Design: Corner/state_machines/cycle_supersede_cascade_on_next_publish
        """
        ctx_a = setup_published_cycle(
            facility_overrides={"name": "F",
                                "cms_certification_number": "CCN-SM5",
                                "bed_count": 50})
        fac, item = ctx_a["facility"], ctx_a["item"]
        cy_a, r_a, f_a = (ctx_a["cycle"], ctx_a["record"], ctx_a["file"])
        # Build the September cycle through FROZEN + VALID file.
        cy_b = create_cycle(fac["id"], period_start="2026-09-01T00:00:00Z",
                            period_end="2026-10-01T00:00:00Z")
        r_b = create_charge_record(fac["id"], cy_b["id"], item["id"],
                                   discounted_cash_cents=51000)
        validate_record(r_b["id"])
        freeze_cycle(cy_b["id"])
        f_b = generate_machine_file(cy_b["id"])
        validate_machine_file(f_b["id"])
        # Publishing the September cycle supersedes the August chain.
        cy_b = publish_cycle(cy_b["id"])
        assert cy_b["status"] == "PUBLISHED"
        assert cy_b["posture"] == "CURRENT"
        cy_a_after = get_success_data(api.get_cycle(cy_a["id"], OFFICER))
        assert cy_a_after["status"] == "SUPERSEDED"
        assert cy_a_after["posture"] == "ARCHIVED"
        # Its record left the counted set (VALIDATED/PUBLISHED/FLAGGED).
        assert cy_a_after["validated_record_count"] == 0
        r_a_after = get_success_data(api.get_charge_record(r_a["id"], OFFICER))
        assert r_a_after["status"] == "SUPERSEDED"
        files, _ = validate_paginated(
            api.list_machine_files(cy_a["id"], OFFICER))
        assert len(files) == 1
        assert files[0]["generation_status"] == "SUPERSEDED"


class TestFileGenerationAndValidation:
    def test_file_generate_on_open_cycle_rejected(self, api):
        """PRD section 3.4: "Against a `FROZEN` cycle — anything else is rejected with `ERR_CYCLE_NOT_FROZEN` — a `TransparencyOfficer` generates the machine-readable file, choosing a `file_format` of `JSON` or `CSV` and passing `publication_cycle_id`; the OCC guard of §2.6 applies to this call."

        Design: Corner/errors/file_generate_on_open_cycle_rejected
        """
        fac = create_facility(name="F", cms_certification_number="CCN-ER2",
                              bed_count=50)
        item = create_service_item(fac["id"], code="70551", description="MRI",
                                   gross_charge_cents=100000)
        cycle = create_cycle(fac["id"])
        create_charge_record(fac["id"], cycle["id"], item["id"],
                             discounted_cash_cents=50000)
        cycle = get_success_data(api.get_cycle(cycle["id"], OFFICER))
        # The OCC version is current; only the state gate can fire.
        resp = api.create_machine_file(
            create_machine_file_payload(cycle["id"], cycle["version"]),
            OFFICER)
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_FROZEN)

    def test_occ_file_generate_stale_cycle_version_rejected(self, api):
        """PRD section 2.6: "A request to generate a `MachineReadableFile` must carry `expected_publication_cycle_version`, holding the cycle `version` the client last observed."
        PRD section 2.6: "If another writer has advanced the cycle's version since that observation — for example by generating a file for the same cycle (which legitimately supersedes the prior sealed file) or by adding or validating records — the generation is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD section 3.4: "The new file is born with `generation_status` `SEALED` and `validation_status` `UNVALIDATED`, the prior `SEALED` file of the same cycle — if any — cascades `SEALED → SUPERSEDED`, and the cycle's `version` increments."

        Design: Corner/cross_cutting_layers/occ_file_generate_stale_cycle_version_rejected
        """
        ctx = setup_frozen_cycle(
            facility_overrides={"name": "F",
                                "cms_certification_number": "CCN-X2L",
                                "bed_count": 50})
        cycle_id = ctx["cycle"]["id"]
        freeze_version = ctx["cycle"]["version"]
        f1 = get_success_data(api.create_machine_file(
            create_machine_file_payload(cycle_id, freeze_version), OFFICER))
        assert f1["generation_status"] == "SEALED"
        assert f1["validation_status"] == "UNVALIDATED"
        # The first generation bumped the cycle version, so the captured
        # freeze-time version is now stale.
        resp = api.create_machine_file(
            create_machine_file_payload(cycle_id, freeze_version), OFFICER)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412
        files, _ = validate_paginated(
            api.list_machine_files(cycle_id, OFFICER))
        sealed = [f for f in files if f["generation_status"] == "SEALED"]
        assert len(sealed) == 1
        assert sealed[0]["id"] == f1["id"]

    def test_superseded_file_cannot_be_validated(self, api):
        """PRD section 3.4: "Schema validation is a separate, repeatable step over a `SEALED` file; validating a file in any other generation status is rejected with `ERR_FILE_NOT_SEALED`."
        PRD section 3.4: "The new file is born with `generation_status` `SEALED` and `validation_status` `UNVALIDATED`, the prior `SEALED` file of the same cycle — if any — cascades `SEALED → SUPERSEDED`, and the cycle's `version` increments."

        Design: Corner/errors/superseded_file_cannot_be_validated
        """
        ctx = setup_frozen_cycle(
            facility_overrides={"name": "F",
                                "cms_certification_number": "CCN-ER3",
                                "bed_count": 50})
        cycle_id = ctx["cycle"]["id"]
        f1 = generate_machine_file(cycle_id)
        _f2 = generate_machine_file(cycle_id, file_format="CSV")  # supersedes F1
        resp = api.validate_machine_file(f1["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_FILE_NOT_SEALED)

    def test_mrf_summary_rollup_snapshot_at_generation(self, api):
        """PRD section 3.4: "Generation serializes the cycle's `VALIDATED` records in ascending order of the service item's billing `code`, ties broken by the record's `created_at` ascending, and stamps the file with `record_count` (the number of records serialized) and `summary_total_discounted_cents` (the sum of those records' `discounted_cash_cents`)."
        PRD section 3.4: "The file is a snapshot: later corrections never mutate a sealed or published file."

        Design: Corner/calculations/mrf_summary_rollup_snapshot_at_generation
        """
        fac = create_facility(name="F", cms_certification_number="CCN-K5",
                              bed_count=50)
        payer = create_payer(name="PA")
        contract = create_contract(fac["id"], payer["id"])
        si1 = create_service_item(fac["id"], code="70551", description="MRI",
                                  gross_charge_cents=100000)
        si2 = create_service_item(fac["id"], code="70450", description="CT",
                                  gross_charge_cents=80000)
        create_rate(contract["id"], si1["id"], rate_percent=40)
        create_rate(contract["id"], si2["id"], rate_percent=50)
        get_success_data(api.activate_contract(contract["id"], MANAGER))
        cycle = create_cycle(fac["id"])
        r1 = create_charge_record(fac["id"], cycle["id"], si1["id"],
                                  discounted_cash_cents=50000)
        r2 = create_charge_record(fac["id"], cycle["id"], si2["id"],
                                  discounted_cash_cents=40000)
        validate_record(r1["id"])
        validate_record(r2["id"])
        freeze_cycle(cycle["id"])
        file_ = generate_machine_file(cycle["id"])
        assert file_["generation_status"] == "SEALED"
        assert file_["validation_status"] == "UNVALIDATED"
        assert file_["record_count"] == 2
        assert file_["summary_total_discounted_cents"] == 90000  # 50000+40000
        validate_machine_file(file_["id"])
        publish_cycle(cycle["id"])
        files, _ = validate_paginated(
            api.list_machine_files(cycle["id"], OFFICER))
        assert len(files) == 1
        # The snapshot is immutable across the publish transition.
        assert files[0]["record_count"] == 2
        assert files[0]["summary_total_discounted_cents"] == 90000


class TestFileValidationLoop:
    def _setup(self, api):
        """Facility (min_records 1) + DISCLOSE contract (40% -> 40000) +
        AGGREGATE_ONLY contract (60% -> 60000), both ACTIVE; one VALIDATED
        record; cycle FROZEN."""
        fac = create_facility(name="F", cms_certification_number="CCN-S2",
                              bed_count=100, min_records_per_cycle=1)
        pa = create_payer(name="PA")
        pb = create_payer(name="PB")
        pc = create_payer(name="PC", payer_type="MEDICAID_MANAGED")
        ca = create_contract(fac["id"], pa["id"], annual_volume=100,
                             confidentiality_clause="DISCLOSE_ALLOWED")
        cb = create_contract(fac["id"], pb["id"], annual_volume=300,
                             confidentiality_clause="AGGREGATE_ONLY")
        item = create_service_item(fac["id"], code="70551", description="MRI",
                                   gross_charge_cents=100000)
        create_rate(ca["id"], item["id"], rate_percent=40)
        create_rate(cb["id"], item["id"], rate_percent=60)
        get_success_data(api.activate_contract(ca["id"], MANAGER))
        get_success_data(api.activate_contract(cb["id"], MANAGER))
        cycle = create_cycle(fac["id"])
        record = create_charge_record(fac["id"], cycle["id"], item["id"],
                                      discounted_cash_cents=50000)
        validate_record(record["id"])
        freeze_cycle(cycle["id"])
        return fac, pc, item, cycle, record

    def test_mrf_invalidate_deidentification_violation(self, api):
        """PRD section 3.4: "And for every linked `VALIDATED` record where an `ACTIVE` `AGGREGATE_ONLY` contract of the facility holds an `ACTIVE` rate for the record's item while the de-identification payer count for that item sits below three, a `DEIDENTIFICATION_VIOLATION` violation tagged with the record's `id` is recorded."
        PRD section 3.4: "An empty violation list moves `validation_status` to `VALID` and clears `validation_errors`; a non-empty list moves it to `INVALID` and stores the codes."

        Design: Difficulty/non_linear_state_machine/mrf_parallel_dimensions_invalidate_and_revalidate_loop
        """
        _fac, _pc, _item, cycle, record = self._setup(api)
        f1 = generate_machine_file(cycle["id"])
        f1 = get_success_data(api.validate_machine_file(f1["id"], OFFICER))
        # Two distinct payers (PA, PB) sit below the de-identification floor.
        assert f1["validation_status"] == "INVALID"
        assert any(e.startswith("DEIDENTIFICATION_VIOLATION")
                   for e in f1["validation_errors"])
        # The failure lives on the validation dimension only: the file stays
        # SEALED on the generation dimension.
        assert f1["generation_status"] == "SEALED"

    def test_mrf_remediation_regenerate_revalidate_loop(self, api):
        """PRD section 3.4: "Re-validation loops — an `INVALID` file may be validated again after remediation, and either outcome may follow either prior state, provided the file remains `SEALED`."
        PRD section 3.3: "The de-identification floor is three distinct payers: a count of exactly three passes, a count of two fails."
        PRD section 3.4: "The new file is born with `generation_status` `SEALED` and `validation_status` `UNVALIDATED`, the prior `SEALED` file of the same cycle — if any — cascades `SEALED → SUPERSEDED`, and the cycle's `version` increments."

        Design: Difficulty/non_linear_state_machine/mrf_parallel_dimensions_invalidate_and_revalidate_loop
        """
        fac, pc, item, cycle, _record = self._setup(api)
        f1 = generate_machine_file(cycle["id"])
        f1 = get_success_data(api.validate_machine_file(f1["id"], OFFICER))
        assert f1["validation_status"] == "INVALID"
        # Remediate: a third ACTIVE contract/payer raises the payer count to
        # exactly three, which passes the floor.
        cc = create_contract(fac["id"], pc["id"], annual_volume=50,
                             confidentiality_clause="DISCLOSE_ALLOWED")
        create_rate(cc["id"], item["id"], rate_percent=50)
        get_success_data(api.activate_contract(cc["id"], MANAGER))
        # Regenerate: the new file supersedes the INVALID one.
        f2 = generate_machine_file(cycle["id"])
        f2 = get_success_data(api.validate_machine_file(f2["id"], OFFICER))
        assert f2["validation_status"] == "VALID"
        assert f2["validation_errors"] == []
        files, _ = validate_paginated(
            api.list_machine_files(cycle["id"], OFFICER))
        by_id = {f["id"]: f for f in files}
        assert by_id[f1["id"]]["generation_status"] == "SUPERSEDED"
        sealed = [f for f in files if f["generation_status"] == "SEALED"]
        assert len(sealed) == 1
        assert sealed[0]["id"] == f2["id"]
