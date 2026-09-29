"""Declared transitions, skipped targets and terminal-state lockdown.

An action is accepted only where the entity's section declares the transition. A
skipped build target, a second grant on an already-granted row and a disposition on
scrapped metal are all refused, while an expired qualification has a declared way back.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    BuildStatus,
    CertStatus,
    ComponentStatus,
    ErrorId,
    QualificationStatus,
    ServiceStatus,
    assert_lot_mass_balance,
    assert_mass,
    assert_unit_dimensions,
    factories,
    fixtures,
    make_procurement_specialist_headers,
    make_quality_manager_headers,
    make_test_technician_headers,
)


# ─── Where a unit starts ───


def test_01_a_newly_opened_unit_starts_blank_uncertified_and_out_of_service(api):
    """Opening a unit consumes its body component and sets all three dimensions to their
    declared opening values at once.

    PRD §3.3: "On success the component moves to `CONSUMED`, and the unit opens with
    `build_status` `BLANK`, `cert_status` `UNCERTIFIED`, `service_status` `NONE`,
    `reserved_kit_qty` 0, `service_engineer_user_id` null, `provisional_emission_leak_class`
    and `final_emission_leak_class` both null, `certified_by_user_id`, `certified_at` and
    `decertification_reason` all null." PRD §3.3: "`qty_committed_kg` is the total
    `net_weight_kg` of components in `CREATED`, `ISSUED_TO_MACHINING`, `CONSUMED` or `HOLD`."

    Design: Corner/state_machines/corner_valve_unit_initial_state_is_blank_uncertified_none
    """
    line = fixtures.build_traceable_line(
        api,
        foundry_code="FDY-C4",
        foundry_name="Corner Opening Castings",
        heat_number="H-C401",
        mtr_document_ref="MTR-C401",
        model_code="BV-300-OPEN",
        release_design=False,
        license_code="MON-C4",
        scope_valve_types=["BALL"],
        grant_license=False,
    )
    fixtures.submit_model_for_review(api, line["model"]["id"])

    unit = fixtures.open_unit(
        api,
        line["model"]["id"],
        line["component"]["id"],
        line["license"]["id"],
        serial_number="SN-C4-1",
    )

    assert_unit_dimensions(
        unit,
        build_status=BuildStatus.BLANK,
        cert_status=CertStatus.UNCERTIFIED,
        service_status=ServiceStatus.NONE,
    )
    assert unit["reserved_kit_qty"] == 0
    assert unit["service_engineer_user_id"] is None
    assert unit["provisional_emission_leak_class"] is None
    assert unit["final_emission_leak_class"] is None
    assert unit["certified_by_user_id"] is None
    assert unit["certified_at"] is None
    assert unit["decertification_reason"] is None
    component = fixtures.read_component(api, line["component"]["id"])
    assert component["status"] == ComponentStatus.CONSUMED
    lot = fixtures.read_lot(api, line["lot"]["id"])
    assert_mass(lot["qty_committed_kg"], 120.500, "qty_committed_kg")
    assert_mass(lot["qty_available_kg"], 379.500, "qty_available_kg")


def test_02_advancing_the_build_two_steps_at_once_is_refused(api):
    """A blank unit may go to machined and no further in one motion, so naming assembled
    as the target is a sequence violation and the build does not move.

    PRD §3.3: "Only the adjacent forward step in the sequence `BLANK → MACHINED → ASSEMBLED
    → PACKAGED → SHIPPED` is accepted; any skipped or backward target is refused with
    `ERR_BUILD_SEQUENCE_INVALID`."

    Design: Corner/state_machines/corner_build_advance_skipping_assembled_rejected
    """
    line = fixtures.build_traceable_line(
        api,
        foundry_code="FDY-C5",
        foundry_name="Corner Sequence Castings",
        heat_number="H-C501",
        mtr_document_ref="MTR-C501",
        model_code="BV-300-SEQ",
        license_code="MON-C5",
        scope_valve_types=["BALL"],
        grant_license=False,
    )
    unit = fixtures.open_unit(
        api,
        line["model"]["id"],
        line["component"]["id"],
        line["license"]["id"],
        serial_number="SN-C5-1",
    )

    response = api.valve_unit_build_action(
        unit["id"],
        factories.advance_build_payload("ASSEMBLED"),
        make_test_technician_headers("tech-c5"),
    )

    validate_error(response, ErrorId.BUILD_SEQUENCE_INVALID, 422)
    unchanged = fixtures.read_unit(api, unit["id"])
    assert_unit_dimensions(
        unchanged, build_status=BuildStatus.BLANK, cert_status=CertStatus.UNCERTIFIED
    )


# ─── Terminal states admit no further disposition ───


def test_03_scrapped_metal_cannot_be_voided_back_into_the_lot(api):
    """Voiding is declared out of `CREATED` and `ISSUED_TO_MACHINING` only, so a scrapped
    component stays scrapped and its mass stays out of what is available.

    PRD §3.3: "Voiding is the compensating disposition for a mis-issued draw: it is
    permitted from `CREATED` or `ISSUED_TO_MACHINING`, requires that no valve unit references
    the component as its `body_component_id` (otherwise `ERR_COMPONENT_NOT_AVAILABLE`),
    removes the mass from `qty_committed_kg` and returns it to `qty_available_kg`." PRD §3.3:
    "Scrapping is permitted from `CREATED`, `ISSUED_TO_MACHINING` or `HOLD` and moves the mass
    from `qty_committed_kg` into `qty_scrapped_kg`, leaving `qty_available_kg` untouched —
    scrapped metal is gone, not returned."

    Design: Corner/state_machines/corner_scrapped_component_cannot_be_voided
    """
    qualified = fixtures.create_qualified_foundry(
        api, foundry_code="FDY-C6", name="Corner Scrap Castings", country_code="IN"
    )
    lot = fixtures.create_released_lot(
        api,
        qualified["foundry"]["id"],
        heat_number="H-C601",
        mtr_document_ref="MTR-C601",
        qty_received_kg=500.000,
    )
    model = fixtures.create_model(api, model_code="BV-300-SCRAP")
    component = fixtures.draw_component(
        api, lot["id"], model["id"], component_type="BONNET", net_weight_kg=60.250
    )
    scrapped = fixtures.dispose_component(api, component["id"], "SCRAP")
    assert scrapped["status"] == ComponentStatus.SCRAPPED

    response = api.component_disposition(
        component["id"],
        factories.component_disposition_payload("VOID"),
        make_procurement_specialist_headers(),
    )

    validate_error(response, ErrorId.STATE_INVALID, 409)
    unchanged = fixtures.read_component(api, component["id"])
    assert unchanged["status"] == ComponentStatus.SCRAPPED
    lot_after = fixtures.read_lot(api, lot["id"])
    assert_mass(lot_after["qty_scrapped_kg"], 60.250, "qty_scrapped_kg")
    assert_mass(lot_after["qty_available_kg"], 439.750, "qty_available_kg")
    assert_lot_mass_balance(lot_after)


def test_04_qualifying_an_already_qualified_row_a_second_time_is_refused(api):
    """`PENDING → QUALIFIED` is the only declared grant, so a second grant is not a
    transition and the first grantor's identity stands.

    PRD §3.2: "The row opens at `status` `PENDING` with `requalification_count` 0 and
    `qualified_by_user_id` null. Qualification states run `PENDING → QUALIFIED`, with
    `EXPIRED` reachable from `QUALIFIED` and `REVOKED` terminal." PRD §2.10: "The requested
    action is a declared transition out of the entity's current state — otherwise
    `ERR_STATE_INVALID` (HTTP 409)."

    Design: Corner/state_machines/corner_second_qualify_on_qualified_row_rejected
    """
    foundry = fixtures.create_foundry(
        api, foundry_code="FDY-C7", name="Corner Regrant Castings", country_code="IN"
    )
    qualification = fixtures.create_qualification(api, foundry["id"])
    granted = fixtures.qualify(
        api, qualification["id"], headers=make_quality_manager_headers("qm-c7")
    )
    assert granted["status"] == QualificationStatus.QUALIFIED

    response = api.foundry_qualification_action(
        qualification["id"],
        factories.qualification_action_payload("QUALIFY"),
        make_quality_manager_headers("qm-c8"),
    )

    validate_error(response, ErrorId.STATE_INVALID, 409)
    unchanged = fixtures.read_qualification(api, qualification["id"])
    assert unchanged["status"] == QualificationStatus.QUALIFIED
    assert unchanged["qualified_by_user_id"] == "qm-c7", "The second caller did not overwrite"
    assert fixtures.read_foundry(api, foundry["id"])["revoked_qualification_count"] == 0


# ─── An expired window has a declared way back ───


def test_05_requalification_reopens_an_expired_window_and_clears_the_grant(api):
    """Once the clock is past the window the row reads as expired, and requalifying it
    supplies a fresh window that must be granted afresh.

    PRD §3.2: "An expired row is not replaced by a fresh one — instead the
    `ProcurementSpecialist` requalifies it, moving `EXPIRED → PENDING` while supplying a new
    `valid_from` and `valid_until`." PRD §3.2: "requalification increments
    `requalification_count` by 1, replaces the window, and resets `qualified_by_user_id` to
    null so the new window must be granted afresh."

    Design: Corner/state_machines/corner_qualification_requalify_reopens_expired_window
    """
    qualified = fixtures.create_qualified_foundry(
        api,
        foundry_code="FDY-C8",
        name="Corner Requalify Castings",
        country_code="IN",
        valid_from="2026-01-01T00:00:00Z",
        valid_until="2026-12-31T00:00:00Z",
    )
    qualification_id = qualified["qualification"]["id"]
    fixtures.set_logical_clock(api, "2027-01-15T00:00:00Z")
    expired = fixtures.read_qualification(api, qualification_id)
    assert expired["status"] == QualificationStatus.EXPIRED

    reopened = get_success_data(
        api.foundry_qualification_action(
            qualification_id,
            factories.qualification_action_payload(
                "REQUALIFY",
                valid_from="2027-02-01T00:00:00Z",
                valid_until="2027-12-31T00:00:00Z",
            ),
            make_procurement_specialist_headers(),
        )
    )

    assert reopened["status"] == QualificationStatus.PENDING
    assert reopened["requalification_count"] == 1
    assert reopened["valid_from"].startswith("2027-02-01T00:00:00")
    assert reopened["valid_until"].startswith("2027-12-31T00:00:00")
    assert reopened["qualified_by_user_id"] is None
