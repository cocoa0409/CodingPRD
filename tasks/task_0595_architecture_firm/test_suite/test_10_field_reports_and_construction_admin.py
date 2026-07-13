"""Construction administration: field reports, their RFI cascade and the completion lock."""
from test_helpers import (
    ApiErrorId, validate_success, validate_error, validate_paginated,
    assert_field_report, assert_rfi, assert_append_only_common_fields,
    state_payload, create_field_report_payload,
    setup_executed_project, setup_project_ready_for_ca,
    activate_phase, file_field_report, read_project, PRINCIPAL,
)


class TestFieldReportDeficiencyCascade:

    def test_a_deficiency_report_auto_creates_exactly_one_open_rfi(self, api):
        """PRD §3.5: "The report row is written, and then the system, on the observer's behalf,
        opens exactly **one** RFI (not three — one per report, regardless of how many deficiencies
        it names). That RFI belongs to the same project, cites no drawing, carries `field_report_id`
        pointing back at the report that spawned it, has an `origin` of `FIELD_REPORT` rather than
        `CONTRACTOR`, has `impacts_fee` of `false`, has a `subject` of exactly `Field deficiency
        follow-up`, sits in status `OPEN`, and takes the next sequential `rfi_number` for the
        project."
        PRD §3.5: "Because the auto-created RFI was never returned to the filer in the field-report
        response, the only way to find it is to list RFIs filtered by that report's
        `field_report_id`."

        Design: Difficulty/transitive_cascade/field_report_deficiency_cascades_rfi_to_open_count_to_ca_posture_to_completion_lock
        """
        bundle = setup_project_ready_for_ca(project_number="FLD-001", name="Field Forum")

        report = file_field_report(
            bundle, deficiency_count=2,
            observations="Two hairline cracks in the slab pour.",
        )
        assert_field_report(report)

        rows, meta = validate_paginated(
            api.list_rfis(bundle["pm_headers"], params={"field_report_id": report["id"]})
        )
        assert meta["total_count"] == 1, "one RFI per report, regardless of the deficiency count"
        assert len(rows) == 1

        cascade_rfi = rows[0]
        assert_rfi(cascade_rfi)
        assert cascade_rfi["origin"] == "FIELD_REPORT"
        assert cascade_rfi["status"] == "OPEN"
        assert cascade_rfi["drawing_id"] is None
        assert cascade_rfi["field_report_id"] == report["id"]
        assert cascade_rfi["impacts_fee"] is False
        assert cascade_rfi["subject"] == "Field deficiency follow-up"

    def test_the_cascade_flips_the_ca_posture_and_freezes_phase_completion(self, api):
        """PRD §3.5: "The project's `open_rfi_count` therefore rises by 1, its `ca_posture` flips to
        `DEFICIENT`, and — as a fourth consequence — every `ACTIVE` phase on that project is now
        barred from completing until that RFI is answered or voided."
        PRD §3.3: "It is barred outright while the project's `ca_posture` is `DEFICIENT` — that is,
        while `open_rfi_count` is greater than zero — with `ERR_OPEN_RFIS_BLOCK_COMPLETION` (§3.4
        explains why)."

        Design: Difficulty/transitive_cascade/field_report_deficiency_cascades_rfi_to_open_count_to_ca_posture_to_completion_lock
        """
        bundle = setup_project_ready_for_ca(project_number="FLD-002", name="Field Forge")

        before = read_project(bundle)
        assert before["open_rfi_count"] == 0
        assert before["ca_posture"] == "CLEAR"

        file_field_report(bundle, deficiency_count=2,
                          observations="Two hairline cracks in the slab pour.")

        after = read_project(bundle)
        assert after["open_rfi_count"] == 1
        assert after["ca_posture"] == "DEFICIENT"

        response = api.set_phase_state(
            bundle["phase_ids"]["CA"], state_payload("COMPLETED"), bundle["pm_headers"]
        )
        validate_error(response, ApiErrorId.ERR_OPEN_RFIS_BLOCK_COMPLETION.value)


class TestFieldReportShapeAndGates:

    def test_a_field_report_is_append_only_and_carries_no_version(self, api):
        """PRD §2.4: "`FieldReport` is the single exception. A field report is an append-only
        observation: once filed, it is never updated and never deleted. It therefore carries only
        `id` and `created_at` — it has **no** `updated_at` field and **no** `version` field, and
        neither key appears in its serialised representation."
        PRD §3.5: "A report filed with a `deficiency_count` of 0 creates no RFI and moves no
        counter."

        Design: Corner/entities/field_report_is_immutable_and_carries_only_id_and_created_at
        """
        bundle = setup_project_ready_for_ca(project_number="IMM-001", name="Immutable Inn")

        report = file_field_report(
            bundle, deficiency_count=0, weather="Clear", observations="Nothing to report."
        )

        fetched = validate_success(
            api.get_field_report(report["id"], bundle["pm_headers"])
        )
        assert_append_only_common_fields(fetched)
        assert_field_report(fetched)
        assert fetched["deficiency_count"] == 0

        _, meta = validate_paginated(
            api.list_rfis(bundle["pm_headers"], params={"field_report_id": report["id"]})
        )
        assert meta["total_count"] == 0, "a deficiency_count of 0 creates no RFI"
        assert read_project(bundle)["open_rfi_count"] == 0

    def test_filing_before_the_ca_phase_is_active_is_rejected(self, api):
        """PRD §3.5: "Filing is gated twice. The project's `CA` phase must exist and be in status
        `ACTIVE` — a site visit before construction administration has begun is rejected with
        `ERR_CA_PHASE_NOT_ACTIVE` — and the project itself must be `ACTIVE`, failing which the
        filing is rejected with `ERR_PROJECT_NOT_ACTIVE`."

        Design: Corner/validations/field_report_before_ca_phase_is_active_is_rejected
        """
        bundle = setup_executed_project(
            project_number="CAX-001", name="CA Not Yet",
            weights=(2500, 2500, 2500, 2500),
        )
        activate_phase(bundle, "SD")  # the CA phase is still NOT_STARTED

        response = api.create_field_report(
            create_field_report_payload(
                bundle["project_id"], bundle["arch_id"],
                weather="Rain", observations="Too early to visit.", deficiency_count=3,
            ),
            bundle["arch_headers"],
        )
        validate_error(response, ApiErrorId.ERR_CA_PHASE_NOT_ACTIVE.value)

        _, meta = validate_paginated(
            api.list_field_reports(
                bundle["pm_headers"], params={"project_id": bundle["project_id"]}
            )
        )
        assert meta["total_count"] == 0
        assert read_project(bundle)["open_rfi_count"] == 0, "the deficiency cascade never fired"
