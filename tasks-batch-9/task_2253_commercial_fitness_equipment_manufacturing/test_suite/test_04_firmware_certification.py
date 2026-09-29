"""Console builds, the certification junction and the withdrawal cascade."""
from test_helpers import (
    assert_instant,
    certify_firmware_certification,
    firmware_certification_payload,
    load_firmware,
    new_equipment_model,
    new_firmware_release,
    new_maintenance_visit,
    new_model_revision,
    read_equipment_model,
    read_firmware_certification,
    read_firmware_release,
    read_maintenance_visit,
    read_pm_program,
    read_serialized_asset,
    read_service_partner,
    receive_parts,
    reject_certification_payload,
    setup_active_pm_program,
    setup_installed_order,
    setup_qualified_revision,
    setup_released_revision,
    submit_firmware_certification,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_release_payload,
)

C700_REVISION = {"revision_code": "C700-R1", "target_cycle_count": 600_000}
RIG_D = {"name": "RIG-D", "parallel_station_count": 2,
         "supported_duty_classes": ["FULL_COMMERCIAL"]}


def _released_c700():
    """A RELEASED CONSOLE_T2 revision with its build already certified."""
    return setup_released_revision(
        "C700",
        revision_overrides=dict(C700_REVISION),
        certification_overrides={"test_report_ref": "RPT-C700-1"},
    )


def _connected_service_estate():
    """A connected asset in service, on an active programme holding three spares."""
    ctx = setup_installed_order(
        revision_ctx=_released_c700(),
        facility_overrides={"account_name": "Velocity Cycle Studio", "freight_zone": "Z1"},
        partner_overrides={"name": "Velocity Service Co", "region": "R_WEST",
                           "certified_categories": ["CONNECTED"]},
    )
    load_firmware(ctx["asset"]["id"], ctx["firmware_release"]["id"])
    ctx["program"] = setup_active_pm_program(
        ctx["facility"]["id"], ctx["partner"]["id"], tier="PRO", visit_interval_days=90
    )
    receive_parts(ctx["partner"]["id"], 20)
    ctx["visit"] = new_maintenance_visit(
        ctx["program"]["id"], ctx["asset"]["id"], ctx["partner"]["id"],
        scheduled_date="2026-09-20T09:00:00Z", reserved_units=3,
    )
    return ctx


def test_withdrawing_a_build_revokes_its_certifications_and_collapses_asset_support(
    api, compliance_officer_headers
):
    """One withdraw call revokes the pairing and rewrites the asset's support window.

    The PRD states that on withdrawal "Every one of the release's own
    certifications whose `cert_status` is `CERTIFIED` moves `CERTIFIED →
    REVOKED`, each such move lowering the release's `certified_revision_count` by
    one" and that "Every serialized asset whose `installed_firmware_release_id`
    is this release has its `connectivity_support_status` set to
    `FIRMWARE_REVOKED`, its `firmware_support_expires_at` set to the release's
    `withdrawn_at`, and its `support_gap_days` recomputed accordingly."

    Design: Difficulty/transitive_cascade/firmware_withdraw_cascade_six_levels
    """
    ctx = _connected_service_estate()
    asset_before = read_serialized_asset(ctx["asset"]["id"])
    assert asset_before["connectivity_support_status"] == "SUPPORTED"
    assert asset_before["support_gap_days"] == 0

    response = api.withdraw_firmware_release(
        ctx["firmware_release"]["id"],
        withdraw_release_payload(
            withdraw_reason="connectivity defect in the CONSOLE_T2 build"),
        compliance_officer_headers,
    )

    release = validate_success(response)
    assert release["status"] == "WITHDRAWN"
    assert_instant(release["withdrawn_at"], "2026-08-01T00:00:00Z", "withdrawn_at")
    assert release["certified_revision_count"] == 0
    certification = read_firmware_certification(ctx["certification"]["id"])
    assert certification["cert_status"] == "REVOKED"
    asset = read_serialized_asset(ctx["asset"]["id"])
    assert asset["connectivity_support_status"] == "FIRMWARE_REVOKED"
    assert_instant(asset["firmware_support_expires_at"], "2026-08-01T00:00:00Z", "firmware_support_expires_at")
    assert_instant(asset["warranty_expires_at"], "2029-07-31T00:00:00Z", "warranty_expires_at")
    assert asset["support_gap_days"] == 1095
    assert asset["status"] == "IN_SERVICE", "the cascade never moves the asset lifecycle"


def test_withdrawal_holds_the_programme_and_releases_the_held_spare_units(
    api, compliance_officer_headers, service_ops_admin_headers
):
    """The same call reaches the programme, the visit and the partner's stock ledger.

    The PRD states that "Every `ACTIVE` preventive-maintenance program covering
    any such asset moves `ACTIVE → NEEDS_REVISION` with `needs_revision_reason`
    set to `FIRMWARE_REVOKED`" and that "Every `SCHEDULED` maintenance visit
    belonging to those programs moves `SCHEDULED → ON_HOLD` with `held_reason`
    set to `PROGRAM_NEEDS_REVISION`, releasing its held spare units back to the
    partner's on-hand stock."

    Design: Difficulty/transitive_cascade/firmware_withdraw_cascade_six_levels
    """
    ctx = _connected_service_estate()
    partner_before = read_service_partner(ctx["partner"]["id"], service_ops_admin_headers)
    assert partner_before["spare_stock_reserved_units"] == 3
    assert partner_before["spare_stock_on_hand_units"] == 17

    validate_success(
        api.withdraw_firmware_release(
            ctx["firmware_release"]["id"],
            withdraw_release_payload(
                withdraw_reason="connectivity defect in the CONSOLE_T2 build"),
            compliance_officer_headers,
        )
    )

    program = read_pm_program(ctx["program"]["id"], service_ops_admin_headers)
    assert program["status"] == "NEEDS_REVISION"
    assert program["needs_revision_reason"] == "FIRMWARE_REVOKED"
    assert program["annual_labor_hours_committed"] == 8.75
    assert program["covered_asset_count"] == 1
    visit = read_maintenance_visit(ctx["visit"]["id"], service_ops_admin_headers)
    assert visit["status"] == "ON_HOLD"
    assert visit["held_reason"] == "PROGRAM_NEEDS_REVISION"
    partner = read_service_partner(ctx["partner"]["id"], service_ops_admin_headers)
    assert partner["spare_stock_received_units"] == 20
    assert partner["spare_stock_reserved_units"] == 0
    assert partner["spare_stock_consumed_units"] == 0
    assert partner["spare_stock_on_hand_units"] == 20
    assert partner["committed_hours"] == 8.75, (
        "a programme needing revision still consumes partner capacity"
    )
    assert partner["coverage_status"] == "ACTIVE"


def test_release_of_a_connected_revision_is_refused_without_a_certified_pairing(
    api, compliance_officer_headers
):
    """A missing certification and a merely submitted one are both refused alike.

    The PRD states that "If the owning model is connected, at least one of the
    revision's own certifications must be in `CERTIFIED`; without one the release
    is refused with `ERR_FIRMWARE_NOT_CERTIFIED`."

    Design: Difficulty/cross_entity_state_dependency/connected_release_blocked_until_firmware_certification_certified
    """
    ctx = setup_qualified_revision("C700", revision_overrides=dict(C700_REVISION))
    assert ctx["model"]["connected"] is True

    validate_error(
        api.release_revision(ctx["revision"]["id"], compliance_officer_headers),
        "ERR_FIRMWARE_NOT_CERTIFIED", 409,
    )

    firmware = new_firmware_release(version_string="FW-2.1.0",
                                    console_platform="CONSOLE_T2")
    certification = submit_firmware_certification(
        firmware["id"], ctx["revision"]["id"], test_report_ref="RPT-C700-1"
    )
    assert certification["cert_status"] == "SUBMITTED"

    validate_error(
        api.release_revision(ctx["revision"]["id"], compliance_officer_headers),
        "ERR_FIRMWARE_NOT_CERTIFIED", 409,
    )
    revision = validate_success(
        api.get_model_revision(ctx["revision"]["id"], compliance_officer_headers)
    )
    assert revision["status"] == "QUALIFIED"
    assert revision["released_at"] is None
    assert read_firmware_release(firmware["id"])["certified_revision_count"] == 0


def test_sign_off_by_a_second_officer_unblocks_the_connected_release(
    api, compliance_officer_headers
):
    """Certification by someone other than the submitter opens the release edge.

    The PRD states that certifying "requires three things: that the officer's
    `X-User-ID` differs from `submitted_by_user_id`, otherwise
    `ERR_SEGREGATION_OF_DUTIES`; that the owning firmware release is still
    `ACTIVE`; and that the target revision's `status` is either `QUALIFIED` or
    `RELEASED`".

    Design: Difficulty/cross_entity_state_dependency/connected_release_blocked_until_firmware_certification_certified
    """
    ctx = setup_qualified_revision("C700", revision_overrides=dict(C700_REVISION))
    firmware = new_firmware_release(version_string="FW-2.1.0",
                                    console_platform="CONSOLE_T2")
    submitted = submit_firmware_certification(
        firmware["id"], ctx["revision"]["id"], test_report_ref="RPT-C700-1"
    )
    assert submitted["submitted_by_user_id"] == "pe-01"
    certified = certify_firmware_certification(submitted["id"], officer_user_id="co-01")
    assert certified["cert_status"] == "CERTIFIED"
    assert certified["certified_by_user_id"] == "co-01"
    assert_instant(certified["certified_at"], "2026-08-01T00:00:00Z", "certified_at")

    response = api.release_revision(ctx["revision"]["id"], compliance_officer_headers)

    revision = validate_success(response)
    assert revision["status"] == "RELEASED"
    assert_instant(revision["released_at"], "2026-08-01T00:00:00Z", "released_at")
    assert revision["verified_cycle_count"] == 500_000
    assert revision["min_required_cycles"] == 500_000
    model = read_equipment_model(ctx["model"]["id"])
    assert model["connected"] is True
    assert model["released_revision_count"] == 1
    assert model["lifecycle_status"] == "ACTIVE"
    release = read_firmware_release(firmware["id"])
    assert release["certified_revision_count"] == 1
    assert release["status"] == "ACTIVE"


def test_one_build_certified_against_two_revisions_counts_two_junction_rows(
    api, compliance_officer_headers
):
    """The junction carries one row per pairing and the count follows the rows.

    The PRD states that "Connectivity certification is the many-to-many junction
    between builds and revisions" and that a release's "`certified_revision_count`
    counts its own certifications whose `cert_status` is `CERTIFIED`."

    Design: Corner/entities/firmware_certification_junction_links_two_revisions_to_one_release
    """
    first = _released_c700()
    second = setup_qualified_revision(
        "C750",
        revision_overrides={"revision_code": "C750-R1", "target_cycle_count": 600_000},
        rig_overrides=RIG_D,
    )
    pending = submit_firmware_certification(
        first["firmware_release"]["id"], second["revision"]["id"],
        test_report_ref="RPT-C750-1",
    )

    response = api.certify_firmware_certification(pending["id"],
                                                   compliance_officer_headers)

    certified = validate_success(response)
    assert certified["cert_status"] == "CERTIFIED"
    assert certified["certified_by_user_id"] == "co-01"
    assert_instant(certified["certified_at"], "2026-08-01T00:00:00Z", "certified_at")
    release = read_firmware_release(first["firmware_release"]["id"])
    assert release["certified_revision_count"] == 2
    rows, meta = validate_paginated(
        api.list_firmware_certifications(
            compliance_officer_headers,
            params={"firmware_release_id": first["firmware_release"]["id"]},
        )
    )
    assert meta["total_count"] == 2
    assert all(row["cert_status"] == "CERTIFIED" for row in rows)
    assert {row["model_revision_id"] for row in rows} == {
        first["revision"]["id"], second["revision"]["id"]
    }
    assert validate_success(
        api.get_model_revision(second["revision"]["id"], compliance_officer_headers)
    )["status"] == "QUALIFIED", "certifying a build does not release the revision"


def test_duplicate_certification_blocks_submitted_and_certified_but_not_rejected(
    api, compliance_officer_headers
):
    """The pair guard covers both live states and reopens once a row is rejected.

    The PRD states that "no certification with `cert_status` `SUBMITTED` or
    `CERTIFIED` may already exist for the same build-and-revision pair, otherwise
    it is `ERR_DUPLICATE_CERTIFICATION`", while rejecting "has no side effect
    beyond the status change."

    Design: Corner/validations/duplicate_certification_blocks_submitted_and_certified_but_not_rejected
    """
    ctx = _released_c700()
    second_build = new_firmware_release(version_string="FW-2.2.0",
                                       console_platform="CONSOLE_T2")

    validate_error(
        api.create_firmware_certification(
            firmware_certification_payload(ctx["firmware_release"]["id"],
                                           ctx["revision"]["id"],
                                           test_report_ref="RPT-C700-DUP"),
            {"X-User-ID": "pe-01", "X-User-Role": "ProductEngineer"},
        ),
        "ERR_DUPLICATE_CERTIFICATION", 409,
    )

    pending = submit_firmware_certification(second_build["id"], ctx["revision"]["id"],
                                            test_report_ref="RPT-C700-2")
    assert pending["cert_status"] == "SUBMITTED"
    validate_error(
        api.create_firmware_certification(
            firmware_certification_payload(second_build["id"], ctx["revision"]["id"],
                                           test_report_ref="RPT-C700-3"),
            {"X-User-ID": "pe-01", "X-User-Role": "ProductEngineer"},
        ),
        "ERR_DUPLICATE_CERTIFICATION", 409,
    )

    rejected = validate_success(
        api.reject_firmware_certification(
            pending["id"],
            reject_certification_payload(rejection_note="connectivity report incomplete"),
            compliance_officer_headers,
        )
    )
    assert rejected["cert_status"] == "REJECTED"

    reopened = submit_firmware_certification(second_build["id"], ctx["revision"]["id"],
                                             test_report_ref="RPT-C700-4")
    assert reopened["cert_status"] == "SUBMITTED"
    _, meta = validate_paginated(
        api.list_firmware_certifications(
            compliance_officer_headers,
            params={"model_revision_id": ctx["revision"]["id"]},
        )
    )
    assert meta["total_count"] == 3
    assert read_firmware_release(second_build["id"])["certified_revision_count"] == 0


def test_console_platform_must_match_and_the_model_must_be_connected(
    api, compliance_officer_headers, product_engineer_headers
):
    """Two different incompatibilities are reported under one code.

    The PRD states that "The build's `console_platform` must equal the revision's
    model `console_platform` and that model must be connected, otherwise the
    submission is `ERR_PLATFORM_INCOMPATIBLE`".

    Design: Corner/validations/console_platform_must_match_and_the_model_must_be_connected
    """
    ctx = _released_c700()
    foreign_build = new_firmware_release(version_string="FW-9.9.9",
                                        console_platform="CONSOLE_X")
    treadmill = new_equipment_model("T900")
    treadmill_revision = new_model_revision(treadmill, "T900",
                                            revision_code="T900-R1",
                                            target_cycle_count=600_000)

    validate_error(
        api.create_firmware_certification(
            firmware_certification_payload(foreign_build["id"], ctx["revision"]["id"],
                                           test_report_ref="RPT-X-1"),
            product_engineer_headers,
        ),
        "ERR_PLATFORM_INCOMPATIBLE", 422,
    )
    validate_error(
        api.create_firmware_certification(
            firmware_certification_payload(ctx["firmware_release"]["id"],
                                           treadmill_revision["id"],
                                           test_report_ref="RPT-X-2"),
            product_engineer_headers,
        ),
        "ERR_PLATFORM_INCOMPATIBLE", 422,
    )

    model = read_equipment_model(treadmill["id"])
    assert model["connected"] is False
    assert model["console_platform"] is None
    _, meta = validate_paginated(
        api.list_firmware_certifications(compliance_officer_headers)
    )
    assert meta["total_count"] == 1, "only the compatible pairing was ever written"
    assert read_firmware_certification(ctx["certification"]["id"])[
        "cert_status"
    ] == "CERTIFIED"
    assert read_firmware_release(foreign_build["id"])["certified_revision_count"] == 0
    assert validate_success(
        api.get_model_revision(ctx["revision"]["id"], compliance_officer_headers)
    )["status"] == "RELEASED"


def test_load_firmware_is_gated_on_a_certified_pairing_not_a_submitted_one(
    api, compliance_officer_headers, product_engineer_headers, order_planner_headers
):
    """The identical load flips from refused to accepted when the pairing is signed off.

    The PRD states that loading firmware requires "there must exist a
    `CERTIFIED`, non-withdrawn certification pairing that build with the asset's
    revision (`ERR_FIRMWARE_NOT_CERTIFIED`). Success writes
    `installed_firmware_release_id` and recomputes the asset's support window."

    Design: Corner/endpoints/load_firmware_is_gated_on_a_certified_pairing_not_a_submitted_one
    """
    ctx = setup_installed_order(
        revision_ctx=_released_c700(),
        partner_overrides={"name": "Velocity Service Co", "region": "R_WEST",
                           "certified_categories": ["CONNECTED"]},
    )
    second_build = new_firmware_release(version_string="FW-2.2.0",
                                        console_platform="CONSOLE_T2")
    pending = submit_firmware_certification(second_build["id"], ctx["revision"]["id"],
                                            test_report_ref="RPT-C700-2")
    version_before = read_serialized_asset(ctx["asset"]["id"],
                                           order_planner_headers)["version"]

    validate_error(
        api.load_firmware(ctx["asset"]["id"],
                          {"firmware_release_id": second_build["id"]},
                          product_engineer_headers),
        "ERR_FIRMWARE_NOT_CERTIFIED", 409,
    )
    assert read_serialized_asset(ctx["asset"]["id"], order_planner_headers)[
        "version"
    ] == version_before

    validate_success(
        api.reject_firmware_certification(
            pending["id"],
            reject_certification_payload(rejection_note="connectivity report incomplete"),
            compliance_officer_headers,
        )
    )
    assert read_firmware_certification(pending["id"])["cert_status"] == "REJECTED"
    resubmitted = submit_firmware_certification(second_build["id"], ctx["revision"]["id"],
                                                test_report_ref="RPT-C700-3")
    certify_firmware_certification(resubmitted["id"])
    assert read_firmware_certification(resubmitted["id"])["cert_status"] == "CERTIFIED"
    assert read_firmware_release(second_build["id"])["certified_revision_count"] == 1

    response = api.load_firmware(ctx["asset"]["id"],
                                 {"firmware_release_id": second_build["id"]},
                                 product_engineer_headers)

    asset = validate_success(response)
    assert asset["installed_firmware_release_id"] == second_build["id"]
    assert asset["status"] == "IN_SERVICE"
    assert asset["connectivity_support_status"] == "SUPPORTED"
    assert asset["version"] == version_before + 1, (
        "only the accepted load touched the asset row"
    )
