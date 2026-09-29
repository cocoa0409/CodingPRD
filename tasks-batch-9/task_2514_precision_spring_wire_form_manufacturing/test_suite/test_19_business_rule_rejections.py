"""Business-rule refusals: the request is well formed and the actor is entitled,
but the shop's own rules say no.

Every scenario here builds a world in which exactly one substantive rule is
broken and every higher-ranked check of the section 2.8 ladder passes, so the
error identifier the server returns is forced. Each test then re-reads the rows
the refused call touched, because a rejection has to be inert: no row created,
no counter moved, no version bumped, no ledger disturbed.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_errors import (
    ERR_BELOW_MINIMUM_ORDER_QUANTITY,
    ERR_BIOCOMPATIBILITY_REQUIRED,
    ERR_CLOCK_NOT_MONOTONIC,
    ERR_DESIGN_LOCKED,
    ERR_DUPLICATE_CHARACTERISTIC,
    ERR_DUPLICATE_CODE,
    ERR_INSUFFICIENT_WIRE,
    ERR_INVALID_SUBGROUP_SIZE,
    ERR_NO_QUALIFIED_RUN,
    ERR_OPEN_SUBMISSION_EXISTS,
    ERR_PACKAGING_NOT_PERMITTED,
    ERR_PPAP_LEVEL_MISMATCH,
    ERR_PPK_BELOW_PROGRAM_FLOOR,
    ERR_PROGRAM_DESIGN_MISMATCH,
    ERR_PROGRAM_NOT_QUOTED,
    ERR_PROGRAM_POSTURE_BLOCKED,
    ERR_QUOTE_FROZEN,
    ERR_RUN_PIECES_EXHAUSTED,
    ERR_TANGLE_RISK_PACKAGING,
    ERR_TEMP_EXCEEDS_OVEN,
    ERR_TOOLING_DESIGN_MISMATCH,
    ERR_WINDOW_IN_PAST,
)
from test_helpers.test_users import (
    DESIGN_ENGINEER_HEADERS,
    PLANT_ADMIN_HEADERS,
    PROCESS_TECHNICIAN_HEADERS,
    PROGRAM_MANAGER_HEADERS,
    QUALITY_INSPECTOR_HEADERS,
)

# Three readings a tenth of a millimetre either side of the 60.0 nominal: mean
# 60.0, Bessel-corrected sigma 0.2, so the binding 0.5 mm distance divided by
# three sigma lands the capability index at 0.833 — under the 1.333 print floor
# and under the program's 1.0 long-run floor.
_MARGINAL_SUBGROUP = [59.8, 60.0, 60.2]
_MARGINAL_CAPABILITY = 0.833

# The instant the clock is asked to fall back to, one day behind the reading it
# already holds.
_EARLIER_INSTANT = "2026-08-04T08:00:00Z"

# A self-consistent setup window that closes two days before the clock's opening
# reading, so the window arithmetic passes and only its pastness refuses it.
_PAST_WINDOW_START = "2026-07-30T08:00:00Z"
_PAST_WINDOW_END = "2026-07-30T12:00:00Z"


def test_revision_of_a_design_carrying_an_in_flight_package_is_refused(api):
    """A `SUBMITTED` package freezes the engineering record of a revisable design.

    PRD §3.3: "Independently of state, the engineering record is frozen once the customer is involved: if any qualification submission of this design is in `SUBMITTED`, `INTERIM_APPROVED` or `APPROVED` status, the revision is refused with `ERR_DESIGN_LOCKED` (HTTP 409)."
    PRD §2.8: "On the revision operation, rank 20 outranks rank 21: an `OBSOLETE` design answers `ERR_DESIGN_INVALID_STATE`, while a design still in a revisable state that carries an in-flight or granted approval package answers `ERR_DESIGN_LOCKED`."

    Design: Corner/errors/design_revision_while_a_package_is_in_flight_rejected
    """
    world = X.build_world(api, "submitted")
    design = X.refresh_design(api, world.design_id)

    # PROTOTYPE_RELEASED is a revisable state, so the higher-ranked state gate
    # passes and the in-flight package is the only rule left to refuse the call.
    assert design["release_status"] == C.RELEASE_PROTOTYPE, (
        f"the design must sit in a revisable state, got {design['release_status']}"
    )
    assert world.submission["submission_status"] == C.SUBMISSION_SUBMITTED, (
        "the package must still be in flight for the lock to bite, got "
        f"{world.submission['submission_status']}"
    )
    version_before = design["version"]

    response = api.revise_design(
        world.design_id,
        F.revision_payload(version_before, active_coils=10),
        DESIGN_ENGINEER_HEADERS,
    )
    validate_error(response, ERR_DESIGN_LOCKED, 409)

    # A refused revision re-runs nothing: the geometry, the engineering stack and
    # the release status all stand where they were.
    frozen = X.refresh_design(api, world.design_id)
    assert frozen["active_coils"] == 8, (
        f"the refused revision must not have taken the coil count, got {frozen['active_coils']}"
    )
    assert frozen["spring_rate_n_per_mm"] == C.D1_SPRING_RATE, (
        "the engineering stack must not have been re-run, got "
        f"{frozen['spring_rate_n_per_mm']}"
    )
    assert frozen["release_status"] == C.RELEASE_PROTOTYPE, (
        f"a refused revision does not drop the design to DRAFT, got {frozen['release_status']}"
    )
    assert frozen["version"] == version_before, (
        f"a refused revision bumps no version, expected {version_before}, got {frozen['version']}"
    )


def test_pricing_a_program_after_full_approval_is_refused(api):
    """Full approval freezes the commercial terms even when nothing was ever priced.

    PRD §3.11: "The program's `quote_frozen` must be false, otherwise `ERR_QUOTE_FROZEN` (HTTP 409) — once the customer has fully approved, the numbers are fixed."
    PRD §3.10: "Hop four sets the program's `quote_frozen` to true — the commercial terms are now contractual and no further quote may be run — and re-derives `delivery_posture`, which reaches `ON_TRACK` on a program with no quarantined lots and no held run."

    Design: Corner/errors/requote_after_the_package_is_approved_rejected
    """
    # A run whose first article is accepted qualifies the package, and the
    # package is put in front of the customer without pricing the program first.
    world = X.build_world(api, "running")
    submission = X.file_submission(api, world.program_id, world.design_id)
    X.customer_verdict(
        api, submission["id"], world.program_id, decision=C.DECISION_APPROVE
    )

    program = X.refresh_program(api, world.program_id)
    assert program["quote_frozen"] is True, "the full approval must have frozen the quote"
    assert program["quoted_unit_price_cents"] is None, (
        "this program was never priced, got "
        f"{program['quoted_unit_price_cents']}"
    )
    version_before = program["version"]

    response = api.quote_program(
        world.program_id,
        F.quote_payload(world.design_id, version_before, quoted_qty=26_000),
        PROGRAM_MANAGER_HEADERS,
    )
    validate_error(response, ERR_QUOTE_FROZEN, 409)

    # The freeze is absolute: a refused quote writes no figure and, because the
    # program's version counter moves only on a successful quote, bumps nothing.
    still = X.refresh_program(api, world.program_id)
    assert still["quoted_unit_price_cents"] is None, (
        f"a refused quote prices nothing, got {still['quoted_unit_price_cents']}"
    )
    assert still["quoted_total_cents"] is None, (
        f"a refused quote writes no contract total, got {still['quoted_total_cents']}"
    )
    assert still["quote_frozen"] is True, "the freeze survives the refused attempt"
    assert still["version"] == version_before, (
        f"a refused quote bumps no version, expected {version_before}, got {still['version']}"
    )


def test_design_on_a_medical_program_refuses_a_non_biocompatible_grade(api):
    """A grade that clears the salt-spray floor still fails the implant-contact gate.

    PRD §3.2: "The chosen material's `salt_spray_hours` must be at least the program's `required_salt_spray_hours`; a shortfall is rejected with `ERR_CORROSION_REQUIREMENT_UNMET` (HTTP 422)."
    PRD §3.2: "And if the program's `biocompatibility_required` is true, the material's `biocompatible` must also be true; otherwise the answer is `ERR_BIOCOMPATIBILITY_REQUIRED` (HTTP 422)."

    Design: Corner/errors/design_create_with_non_biocompatible_wire_on_a_medical_program_rejected
    """
    program = X.open_program(
        api,
        program_code="PGM-MED",
        application_class=C.CLASS_MEDICAL_IMPLANT,
        biocompatibility_required=True,
        required_salt_spray_hours=96,
    )
    material = X.register_material(api)

    # The corrosion gate is the higher-ranked of the two metallurgical checks and
    # it passes exactly at the boundary, leaving biocompatibility to answer alone.
    assert material["salt_spray_hours"] == program["required_salt_spray_hours"], (
        "the coating must meet the salt-spray floor exactly so the corrosion gate "
        f"cannot answer, got {material['salt_spray_hours']} against "
        f"{program['required_salt_spray_hours']}"
    )
    assert material["biocompatible"] is False, (
        "the grade must not be qualified for implant contact for this gate to bite"
    )

    response = api.create_design(
        F.design_payload(program["id"], material["id"]), DESIGN_ENGINEER_HEADERS
    )
    validate_error(response, ERR_BIOCOMPATIBILITY_REQUIRED, 422)

    # The gates run before anything is persisted, so no design row exists at all.
    designs, meta = validate_paginated(api.list_designs(DESIGN_ENGINEER_HEADERS))
    assert meta["total_count"] == 0, (
        f"the refused creation persisted no design, got {meta['total_count']}"
    )
    assert designs == [], "a refused design creation leaves the collection empty"


def test_allocation_is_refused_by_the_worst_subgroup_the_run_ever_took(api):
    """A released hold does not erase the 0.833 Ppk the run already stamped.

    PRD §3.7: "`ppk_value` is the pooled long-run capability and is **null on every first-article record**."
    PRD §3.7: "Each record keeps the pooled figure it was stamped with at its own creation — earlier rows are never restamped when a later subgroup arrives."
    PRD §3.7: "At the run level, `min_cpk_observed` is refreshed to the lowest `cpk_value` across all of the run's inspection records, while `min_ppk_observed` is refreshed to the lowest `ppk_value` across only those of the run's records whose `record_kind` is `SPC` and whose characteristic has `is_safety_critical` true."
    PRD §3.11: "The run's `min_ppk_observed` must be non-null and at least the program's `required_ppk`, otherwise `ERR_PPK_BELOW_PROGRAM_FLOOR` (HTTP 422) — a run that has never taken a safety-critical SPC subgroup has a null `min_ppk_observed` and fails here."

    Design: Corner/errors/lot_create_below_the_program_capability_floor_rejected
    """
    world = X.build_world(api, "running")
    characteristic = world.characteristics[0]

    # The first in-process subgroup pools only itself, so its own Ppk is 0.833 and
    # the safety-critical characteristic drives the run onto a hold.
    X.record_spc_subgroup(api, world.run_id, characteristic, _MARGINAL_SUBGROUP)
    # A second, in-control subgroup is the evidence the RELEASE verdict demands;
    # it pools to a healthier figure but never restamps the first row.
    X.record_spc_subgroup(api, world.run_id, characteristic)
    get_success_data(
        api.quality_disposition(
            world.run_id, {"decision": C.DECISION_RELEASE}, QUALITY_INSPECTOR_HEADERS
        )
    )

    # Everything downstream of capability is then made perfect: the run closes
    # out, is stress relieved and peened, the program is priced and approved.
    X.complete_run(api, world.run_id)
    oven = X.commission_oven(api)
    batch = X.schedule_batch(api, oven["id"], world.run_id, peening_requested=True)
    X.pin_clock(api, batch["window_start"])
    X.start_batch(api, batch["id"])
    X.discharge_batch(api, batch["id"], True)
    program = X.price_program(api, world.program, world.design_id)
    submission = X.file_submission(api, program["id"], world.design_id)
    X.customer_verdict(api, submission["id"], program["id"], decision=C.DECISION_APPROVE)

    run = X.refresh_run(api, world.run_id)
    assert run["quality_status"] == C.QUALITY_OPEN, (
        f"the hold must have been lifted so no higher gate answers, got {run['quality_status']}"
    )
    assert run["min_ppk_observed"] == _MARGINAL_CAPABILITY, (
        f"the historic pooled Ppk must still stand at 0.833, got {run['min_ppk_observed']}"
    )
    assert run["min_ppk_observed"] < program["required_ppk"], (
        "the observed Ppk must sit under the program floor for this gate to bite"
    )

    response = api.create_lot(
        F.lot_payload(world.run_id, program["id"], 1_000), PROGRAM_MANAGER_HEADERS
    )
    validate_error(response, ERR_PPK_BELOW_PROGRAM_FLOOR, 422)

    settled = X.refresh_run(api, world.run_id)
    assert settled["min_ppk_observed"] == _MARGINAL_CAPABILITY, (
        f"a refused allocation restamps no capability figure, got {settled['min_ppk_observed']}"
    )
    assert settled["min_cpk_observed"] == _MARGINAL_CAPABILITY, (
        f"the worst short-run index across every record is 0.833, got {settled['min_cpk_observed']}"
    )
    assert settled["heat_treat_state"] == C.HEAT_TREAT_COMPLETE, (
        f"stress relief stands finished, got {settled['heat_treat_state']}"
    )
    assert settled["peening_verified"] is True, "the peening the design demands was honoured"

    lots, meta = validate_paginated(api.list_lots(PROGRAM_MANAGER_HEADERS))
    assert meta["total_count"] == 0, (
        f"the refused allocation created no lot, got {meta['total_count']}"
    )
    assert lots == [], "no lot exists on a run barred by the capability floor"

    final = X.refresh_program(api, program["id"])
    assert final["allocated_pieces"] == 0, (
        f"a refused allocation allocates nothing, got {final['allocated_pieces']}"
    )
    A.assert_commitment_conserved(final)


def test_shipping_after_the_interim_verdict_is_withdrawn_is_refused(api):
    """A resubmit pulls the posture out from under a lot already on the dock.

    PRD §2.8: "When a single request violates more than one rule, exactly one error is returned: the one with the **lowest priority number** in the following ladder."
    PRD §2.8: "44. `ERR_PROGRAM_POSTURE_BLOCKED` — on `POST /shipment-lots`, `POST /shipment-lots/{id}/ship`."
    PRD §2.8: "76. `ERR_TOOLING_NOT_AMORTIZING` — on `POST /shipment-lots/{id}/ship`."
    PRD §3.10: "Resubmitting from `INTERIM_APPROVED` therefore withdraws the cap that was letting the program allocate pieces, and the re-derived `delivery_posture` returns to `BLOCKED` while no verdict is in force — lots already allocated stay allocated, but no new one can be created until the next verdict lands."
    PRD §3.11: "The program's `delivery_posture` must not be `BLOCKED`, otherwise `ERR_PROGRAM_POSTURE_BLOCKED` — and this is the endpoint where that error is genuinely reachable, because a lot packed while the program was healthy can be presented after a resubmit dropped the posture back to `BLOCKED`."
    PRD §3.11: "The design's newest tooling asset must have an `amortization_status` of `AMORTIZING` or `FULLY_AMORTIZED`, otherwise `ERR_TOOLING_NOT_AMORTIZING` (HTTP 409) — this is the gate that holds interim-approved lots in the warehouse."
    PRD §3.11: "`tooling_recovery_cents` starts at 0 and `shipped_at` and `quarantine_reason` start null."

    Design: Corner/errors/ship_after_the_interim_verdict_is_withdrawn_rejected
    """
    world = X.interim_approved_world(api, interim_piece_cap=5_000)
    lot = X.allocate_lot(api, world.run_id, world.program_id, 1_000)
    X.pack_lot(api, lot["id"], C.PACK_TANGLE_FREE_TRAY)

    # The package goes back for another round, which withdraws the cap and, with
    # no verdict of record left in force, re-derives the posture to BLOCKED.
    get_success_data(
        api.resubmit_submission(world.submission_id, PROGRAM_MANAGER_HEADERS)
    )
    program = X.refresh_program(api, world.program_id)
    assert program["delivery_posture"] == C.POSTURE_BLOCKED, (
        f"the withdrawn verdict must block the program, got {program['delivery_posture']}"
    )

    # The tool never left PENDING, because only a full approval arms amortization
    # — so the rank-76 gate is armed too and the posture must outrank it.
    tool = X.refresh_tooling(api, world.tooling_id)
    assert tool["amortization_status"] == C.AMORT_PENDING, (
        f"an interim verdict arms no amortization, got {tool['amortization_status']}"
    )

    response = api.ship_lot(lot["id"], PROGRAM_MANAGER_HEADERS)
    validate_error(response, ERR_PROGRAM_POSTURE_BLOCKED, 409)

    # Nothing shipped, so no recovery was posted on either side of the ledger.
    held = X.refresh_lot(api, lot["id"])
    assert held["lot_status"] == C.LOT_PACKED, (
        f"the refused shipment leaves the lot on the dock, got {held['lot_status']}"
    )
    assert held["shipped_at"] is None, (
        f"a refused shipment stamps no despatch instant, got {held['shipped_at']}"
    )
    assert held["tooling_recovery_cents"] == 0, (
        f"a refused shipment posts no recovery, got {held['tooling_recovery_cents']}"
    )

    tool_after = X.refresh_tooling(api, world.tooling_id)
    assert tool_after["amortization_status"] == C.AMORT_PENDING, (
        f"a refused shipment arms no tool, got {tool_after['amortization_status']}"
    )
    assert tool_after["recovered_cents"] == 0, (
        f"a refused shipment recovers no cost, got {tool_after['recovered_cents']}"
    )
    A.assert_tooling_ledger_conserved(tool_after)

    final = X.refresh_program(api, world.program_id)
    assert final["delivery_posture"] == C.POSTURE_BLOCKED, (
        f"the refusal changes no posture, got {final['delivery_posture']}"
    )
    assert final["shipped_pieces"] == 0, (
        f"a refused shipment ships no piece, got {final['shipped_pieces']}"
    )
    assert final["allocated_pieces"] == 1_000, (
        f"the thousand pieces stay allocated, got {final['allocated_pieces']}"
    )
    A.assert_commitment_conserved(final)


def test_bulk_box_packaging_on_a_medical_program_is_refused(api):
    """A device program's permitted set has no room for a bulk box.

    PRD §3.11: "First, the method must be in the permitted set for the program's `application_class`: `MEDICAL_IMPLANT` and `MEDICAL_DEVICE` permit only `CLEANROOM_DOUBLE_BAG` and `INTERLEAVED_TUBE`; `AUTOMOTIVE_SAFETY` permits only `TANGLE_FREE_TRAY` and `INTERLEAVED_TUBE`; `AUTOMOTIVE_NON_SAFETY` permits those two plus `BAG_AND_TAG`; `INDUSTRIAL` permits all five."
    PRD §3.11: "A method outside the set answers `ERR_PACKAGING_NOT_PERMITTED` (HTTP 422)."
    PRD §3.11: "Second, independently of class, a design whose `tangle_risk_class` is `HIGH` may not be packed in `BULK_BOX` or `BAG_AND_TAG`, which answers `ERR_TANGLE_RISK_PACKAGING` (HTTP 422)."
    PRD §3.11: "Success records the method and moves the lot `ALLOCATED → PACKED`."

    Design: Corner/errors/bulk_box_packaging_on_a_medical_program_rejected
    """
    world = X.allocated_world(
        api,
        program={"program_code": "PGM-MED", "application_class": C.CLASS_MEDICAL_DEVICE},
    )

    # The second, class-independent rule is deliberately disarmed: this coil is
    # three diameters long, so only the permitted-set rule can answer.
    assert world.design["tangle_risk_class"] == C.TANGLE_LOW, (
        f"the form must not be a high-tangle one, got {world.design['tangle_risk_class']}"
    )

    response = api.pack_lot(
        world.lot_id, {"packaging_method": C.PACK_BULK_BOX}, PROCESS_TECHNICIAN_HEADERS
    )
    validate_error(response, ERR_PACKAGING_NOT_PERMITTED, 422)

    unpacked = X.refresh_lot(api, world.lot_id)
    assert unpacked["lot_status"] == C.LOT_ALLOCATED, (
        f"a refused pack leaves the lot ALLOCATED, got {unpacked['lot_status']}"
    )
    assert unpacked["packaging_method"] is None, (
        f"a refused pack records no method, got {unpacked['packaging_method']}"
    )

    design = X.refresh_design(api, world.design_id)
    assert design["tangle_risk_class"] == C.TANGLE_LOW, (
        f"the refusal reclassifies nothing, got {design['tangle_risk_class']}"
    )

    # The same lot in a method the class does permit is accepted, which proves the
    # method rather than the lot was the defect.
    packed = validate_success(
        api.pack_lot(
            world.lot_id,
            {"packaging_method": C.PACK_CLEANROOM_DOUBLE_BAG},
            PROCESS_TECHNICIAN_HEADERS,
        ),
        200,
    )
    assert packed["lot_status"] == C.LOT_PACKED, (
        f"a permitted method packs the lot, got {packed['lot_status']}"
    )
    assert packed["packaging_method"] == C.PACK_CLEANROOM_DOUBLE_BAG, (
        f"the permitted method is recorded, got {packed['packaging_method']}"
    )


def test_bag_and_tag_packaging_of_a_high_tangle_form_is_refused(api):
    """A slender coil is barred from a bag even on a class that permits one.

    PRD §3.2: "`tangle_risk_index` is the free length divided by the outer diameter, rounded half up to three decimal places."
    PRD §3.2: "`tangle_risk_class` is `HIGH` when that index is at least 4.000 **or** the `end_type` is `HOOK_EXTENSION`, and `LOW` in every other case."
    PRD §3.11: "Second, independently of class, a design whose `tangle_risk_class` is `HIGH` may not be packed in `BULK_BOX` or `BAG_AND_TAG`, which answers `ERR_TANGLE_RISK_PACKAGING` (HTTP 422)."
    PRD §3.11: "The two rules can both bite — an `AUTOMOTIVE_NON_SAFETY` program carrying a high-tangle extension spring cannot use `BAG_AND_TAG` even though its class permits it, and there the class rule passes while the tangle rule rejects."

    Design: Corner/errors/bag_and_tag_packaging_of_a_high_tangle_form_rejected
    """
    # Ninety millimetres of free length over a twenty-millimetre outer diameter.
    world = X.allocated_world(api, design={"free_length_mm": 90.0})

    assert world.program["application_class"] == C.CLASS_INDUSTRIAL, (
        "the class must permit all five methods so the first rule cannot answer, got "
        f"{world.program['application_class']}"
    )
    assert world.design["tangle_risk_index"] == 4.500, (
        f"90.0 over 20.0 is 4.500, got {world.design['tangle_risk_index']}"
    )
    assert world.design["tangle_risk_class"] == C.TANGLE_HIGH, (
        f"an index at or above 4.000 classifies HIGH, got {world.design['tangle_risk_class']}"
    )

    response = api.pack_lot(
        world.lot_id,
        {"packaging_method": C.PACK_BAG_AND_TAG},
        PROCESS_TECHNICIAN_HEADERS,
    )
    validate_error(response, ERR_TANGLE_RISK_PACKAGING, 422)

    unpacked = X.refresh_lot(api, world.lot_id)
    assert unpacked["lot_status"] == C.LOT_ALLOCATED, (
        f"a refused pack leaves the lot ALLOCATED, got {unpacked['lot_status']}"
    )
    assert unpacked["packaging_method"] is None, (
        f"a refused pack records no method, got {unpacked['packaging_method']}"
    )

    design = X.refresh_design(api, world.design_id)
    assert design["tangle_risk_index"] == 4.500, (
        f"the refusal recomputes no index, got {design['tangle_risk_index']}"
    )
    assert design["tangle_risk_class"] == C.TANGLE_HIGH, (
        f"the refusal reclassifies nothing, got {design['tangle_risk_class']}"
    )

    # A method the tangle rule does not bar takes the very same lot.
    packed = validate_success(
        api.pack_lot(
            world.lot_id,
            {"packaging_method": C.PACK_INTERLEAVED_TUBE},
            PROCESS_TECHNICIAN_HEADERS,
        ),
        200,
    )
    assert packed["lot_status"] == C.LOT_PACKED, (
        f"an interleaved tube contains a high-tangle form, got {packed['lot_status']}"
    )
    assert packed["packaging_method"] == C.PACK_INTERLEAVED_TUBE, (
        f"the accepted method is recorded, got {packed['packaging_method']}"
    )


def test_booking_a_setup_with_another_designs_tooling_is_refused(api):
    """A tool set capitalised against a sibling part cannot be mounted for this one.

    PRD §3.6: "The design must have reached a released state — its `release_status` must be `PROTOTYPE_RELEASED` or `PRODUCTION_RELEASED`, and a `DRAFT`, `ENG_REVIEW`, `REJECTED` or `OBSOLETE` design answers `ERR_PPAP_NOT_APPROVED` (HTTP 422)."
    PRD §3.6: "The named tool must belong to that same design, or the booking answers `ERR_TOOLING_DESIGN_MISMATCH` (HTTP 422)."

    Design: Corner/errors/setup_create_with_another_designs_tooling_rejected
    """
    world = X.prototype_world(api)
    sibling = X.draft_design(api, world.program_id, world.material_id, part_number="D2")
    other_tool = X.capitalise_tooling(api, sibling["id"], tool_code="TL-2")
    machine = X.commission_machine(api)

    # The design named in the body is released, so the higher-ranked standing gate
    # passes and only the tool's ownership is wrong.
    assert world.design["release_status"] == C.RELEASE_PROTOTYPE, (
        f"the named design must be released, got {world.design['release_status']}"
    )
    assert other_tool["design_id"] == sibling["id"], (
        f"the tool must belong to the sibling design, got {other_tool['design_id']}"
    )

    response = api.create_setup(
        F.setup_payload(
            machine["id"], world.design_id, other_tool["id"], machine["version"]
        ),
        PROCESS_TECHNICIAN_HEADERS,
    )
    validate_error(response, ERR_TOOLING_DESIGN_MISMATCH, 422)

    setups, meta = validate_paginated(api.list_setups(PROCESS_TECHNICIAN_HEADERS))
    assert meta["total_count"] == 0, (
        f"the refused booking created no setup, got {meta['total_count']}"
    )
    assert setups == [], "no setup row survives a refused booking"

    idle = X.refresh_machine(api, machine["id"])
    assert idle["machine_state"] == C.MACHINE_IDLE, (
        f"a refused booking leaves the coiler idle, got {idle['machine_state']}"
    )

    untouched = X.refresh_tooling(api, other_tool["id"])
    assert untouched["amortization_status"] == C.AMORT_PENDING, (
        f"a refused booking arms no tool, got {untouched['amortization_status']}"
    )


def test_filing_a_package_under_a_foreign_program_is_refused(api):
    """A package may only be filed under the program its design was drawn for.

    PRD §3.10: "The design must exist and its `release_status` must be `PROTOTYPE_RELEASED` — a `DRAFT`, `ENG_REVIEW`, `PRODUCTION_RELEASED`, `REJECTED` or `OBSOLETE` design cannot be submitted and answers `ERR_DESIGN_INVALID_STATE` (HTTP 409)."
    PRD §3.10: "The design's `program_id` must equal the body's `program_id`, otherwise `ERR_PROGRAM_DESIGN_MISMATCH` (HTTP 422)."
    PRD §3.1: "If no submission of the program is in either granted status, the posture is `BLOCKED`."

    Design: Corner/errors/submission_of_a_design_that_belongs_to_another_program_rejected
    """
    world = X.build_world(api, "running")
    other = X.open_program(
        api, program_code="PGM-2", customer_name="Halloway Fastener Group"
    )

    # The design is released and first-article qualified, so every gate above the
    # ownership check passes and the foreign program is the only defect.
    assert world.design["release_status"] == C.RELEASE_PROTOTYPE, (
        f"the design must be submittable, got {world.design['release_status']}"
    )
    assert world.run["fai_disposition"] == C.FAI_ACCEPTED, (
        f"the qualifying run must be on file, got {world.run['fai_disposition']}"
    )
    assert other["ppap_level"] == world.program["ppap_level"], (
        "both programs must declare the same level so no level gate answers, got "
        f"{other['ppap_level']} against {world.program['ppap_level']}"
    )

    response = api.create_submission(
        F.submission_payload(other["id"], world.design_id), PROGRAM_MANAGER_HEADERS
    )
    validate_error(response, ERR_PROGRAM_DESIGN_MISMATCH, 422)

    submissions, meta = validate_paginated(
        api.list_submissions(PROGRAM_MANAGER_HEADERS)
    )
    assert meta["total_count"] == 0, (
        f"the refused filing created no package, got {meta['total_count']}"
    )
    assert submissions == [], "no package exists after a refused filing"

    design = X.refresh_design(api, world.design_id)
    assert design["release_status"] == C.RELEASE_PROTOTYPE, (
        f"a refused filing promotes nothing, got {design['release_status']}"
    )

    stranger = X.refresh_program(api, other["id"])
    assert stranger["delivery_posture"] == C.POSTURE_BLOCKED, (
        "the foreign program still has no granted approval on file, got "
        f"{stranger['delivery_posture']}"
    )


def test_filing_a_package_at_the_wrong_ppap_level_is_refused(api):
    """The program's declared level and the package's claimed level are one number.

    PRD §3.10: "The body's `ppap_level` must equal the program's `ppap_level`, otherwise `ERR_PPAP_LEVEL_MISMATCH` (HTTP 422) — the customer's declared submission level and the package's claimed level are one number, not two."
    PRD §3.10: "A successful filing opens at `round_no` 1 in `submission_status` `SUBMITTED` with `submitted_by_user_id` stamped from the header, `interim_piece_cap`, `reviewed_by_program_id` and `decided_at` all null."

    Design: Corner/errors/submission_at_the_wrong_ppap_level_rejected
    """
    world = X.build_world(api, "running")
    assert world.program["ppap_level"] == 1, (
        f"the program must be a level-1 program, got {world.program['ppap_level']}"
    )

    response = api.create_submission(
        F.submission_payload(world.program_id, world.design_id, ppap_level=3),
        PROGRAM_MANAGER_HEADERS,
    )
    validate_error(response, ERR_PPAP_LEVEL_MISMATCH, 422)

    _submissions, meta = validate_paginated(
        api.list_submissions(PROGRAM_MANAGER_HEADERS)
    )
    assert meta["total_count"] == 0, (
        f"the refused filing created no package, got {meta['total_count']}"
    )

    # The very same body carrying the program's own level is accepted, which shows
    # the level and nothing else was the defect.
    filed = validate_success(
        api.create_submission(
            F.submission_payload(world.program_id, world.design_id, ppap_level=1),
            PROGRAM_MANAGER_HEADERS,
        ),
        201,
    )
    assert filed["submission_status"] == C.SUBMISSION_SUBMITTED, (
        f"a matching level opens the package, got {filed['submission_status']}"
    )
    assert filed["round_no"] == 1, (
        f"a successful filing opens at round 1, got {filed['round_no']}"
    )


def test_first_article_subgroup_of_two_measurements_is_refused(api):
    """Two readings leave no Bessel-corrected standard deviation to compute.

    PRD §3.7: "And the subgroup must contain at least three measurements — below that there is no Bessel-corrected standard deviation to compute — otherwise `ERR_INVALID_SUBGROUP_SIZE` (HTTP 422)."
    PRD §3.7: "A newly opened run starts on both axes at rest — `process_status` `FAI_PENDING`, `quality_status` `OPEN`, `fai_disposition` `PENDING`, `heat_treat_state` `NOT_STARTED`, `peening_verified` false, `produced_pieces` and `scrapped_pieces` at 0, `wire_consumed_kg` at 0.000, and both `min_cpk_observed` and `min_ppk_observed` null."

    Design: Corner/errors/fai_subgroup_of_two_measurements_rejected
    """
    world = X.run_world(api)

    # Both higher-ranked gates pass: the run is FAI_PENDING and the characteristic
    # belongs to the run's own design.
    assert world.run["process_status"] == C.PROCESS_FAI_PENDING, (
        f"the run must be awaiting its first article, got {world.run['process_status']}"
    )
    plan, _plan_meta = validate_paginated(
        api.list_characteristics(world.design_id, DESIGN_ENGINEER_HEADERS)
    )
    assert [row["id"] for row in plan] == [world.characteristic_id], (
        "the characteristic measured must be one of the run's own design's plan"
    )

    response = api.record_fai(
        world.run_id,
        {"characteristic_id": world.characteristic_id, "measurements": [59.95, 60.0]},
        QUALITY_INSPECTOR_HEADERS,
    )
    validate_error(response, ERR_INVALID_SUBGROUP_SIZE, 422)

    records, meta = validate_paginated(
        api.list_inspection_records(QUALITY_INSPECTOR_HEADERS)
    )
    assert meta["total_count"] == 0, (
        f"the refused subgroup persisted no record, got {meta['total_count']}"
    )
    assert records == [], "no inspection record exists after a refused subgroup"

    run = X.refresh_run(api, world.run_id)
    assert run["min_cpk_observed"] is None, (
        f"no record means no observed capability, got {run['min_cpk_observed']}"
    )
    assert run["fai_disposition"] == C.FAI_PENDING, (
        f"the first-article verdict is still open, got {run['fai_disposition']}"
    )
    assert run["process_status"] == C.PROCESS_FAI_PENDING, (
        f"a refused subgroup advances no axis, got {run['process_status']}"
    )


def test_second_characteristic_with_the_same_code_is_refused(api):
    """A design's control plan may name each characteristic code once.

    PRD §3.3: "A characteristic declares `char_code`, one of `FREE_LENGTH`, `SPRING_RATE`, `OUTER_DIAMETER`, `COIL_COUNT`, `HOOK_POSITION` or `LOAD_AT_HEIGHT`, and that code must be unique within the design — a second characteristic carrying a code the design already has is rejected with `ERR_DUPLICATE_CHARACTERISTIC` (HTTP 409)."

    Design: Corner/errors/second_characteristic_with_the_same_code_rejected
    """
    world = X.draft_design_world(api)

    # The design is still DRAFT, so the state gate passes and only the repeated
    # code can refuse the addition.
    assert world.design["release_status"] == C.RELEASE_DRAFT, (
        f"the plan must still be open for additions, got {world.design['release_status']}"
    )
    assert world.characteristics[0]["char_code"] == C.CHAR_FREE_LENGTH, (
        f"the design already carries this code, got {world.characteristics[0]['char_code']}"
    )

    response = api.add_characteristic(
        world.design_id,
        F.characteristic_payload(lsl=59.0, usl=61.0),
        DESIGN_ENGINEER_HEADERS,
    )
    validate_error(response, ERR_DUPLICATE_CHARACTERISTIC, 409)

    rows, meta = validate_paginated(
        api.list_characteristics(world.design_id, DESIGN_ENGINEER_HEADERS)
    )
    assert meta["total_count"] == 1, (
        f"the refused addition left the plan at one row, got {meta['total_count']}"
    )
    # The wider limits of the refused body must not have leaked onto the survivor.
    assert rows[0]["lsl"] == 59.5, (
        f"the surviving row keeps its own lower limit, got {rows[0]['lsl']}"
    )
    assert rows[0]["usl"] == 60.5, (
        f"the surviving row keeps its own upper limit, got {rows[0]['usl']}"
    )


def test_second_program_with_the_same_code_is_refused(api):
    """A program code is claimed once across the whole collection.

    PRD §3.1: "Uniqueness is enforced across six collections and always answers the same code."
    PRD §3.1: "If a supplied `program_code`, `spec_code`, `heat_number`, `tool_code`, `machine_code` or `oven_code` already exists in its own collection, the creation is rejected with `ERR_DUPLICATE_CODE` (HTTP 409)."

    Design: Corner/errors/second_program_with_the_same_code_rejected
    """
    first = X.open_program(api)
    assert first["application_class"] == C.CLASS_INDUSTRIAL, (
        f"the incumbent program is the industrial one, got {first['application_class']}"
    )

    response = api.create_program(
        F.program_payload(application_class=C.CLASS_AUTOMOTIVE_NON_SAFETY),
        PROGRAM_MANAGER_HEADERS,
    )
    validate_error(response, ERR_DUPLICATE_CODE, 409)

    rows, meta = validate_paginated(api.list_programs(PROGRAM_MANAGER_HEADERS))
    assert meta["total_count"] == 1, (
        f"the refused creation left one program standing, got {meta['total_count']}"
    )
    assert rows[0]["id"] == first["id"], "the survivor is the program that was there first"
    assert rows[0]["application_class"] == C.CLASS_INDUSTRIAL, (
        "the refused body must not have overwritten the incumbent's class, got "
        f"{rows[0]['application_class']}"
    )


def test_second_open_package_for_the_same_pair_is_refused(api):
    """One program-and-design pair carries at most one undecided package.

    PRD §3.10: "No other submission for the same `program_id` and `design_id` pair may be in flight or partially granted, that is, none may have a `submission_status` of `SUBMITTED`, `INTERIM_APPROVED` or `REVISION_REQUESTED`, otherwise `ERR_OPEN_SUBMISSION_EXISTS` (HTTP 409); a pair whose only prior submission is `APPROVED` or `REJECTED_FINAL` may be filed again."

    Design: Corner/errors/second_open_package_for_the_same_pair_rejected
    """
    world = X.build_world(api, "submitted")
    assert world.submission["submission_status"] == C.SUBMISSION_SUBMITTED, (
        f"the incumbent package must be undecided, got {world.submission['submission_status']}"
    )

    response = api.create_submission(
        F.submission_payload(world.program_id, world.design_id),
        PROGRAM_MANAGER_HEADERS,
    )
    validate_error(response, ERR_OPEN_SUBMISSION_EXISTS, 409)

    rows, meta = validate_paginated(api.list_submissions(PROGRAM_MANAGER_HEADERS))
    assert meta["total_count"] == 1, (
        f"the refused filing left one package standing, got {meta['total_count']}"
    )
    assert rows[0]["id"] == world.submission_id, "the survivor is the package filed first"

    incumbent = X.refresh_submission(api, world.submission_id)
    assert incumbent["submission_status"] == C.SUBMISSION_SUBMITTED, (
        f"the refusal moves no status, got {incumbent['submission_status']}"
    )
    assert incumbent["round_no"] == 1, (
        f"the refusal opens no new round, got {incumbent['round_no']}"
    )


def test_filing_a_package_without_an_accepted_first_article_is_refused(api):
    """A released print is not evidence the part can actually be made.

    PRD §3.10: "Finally there must be evidence the part can actually be made: at least one production run on that `design_id` must carry a `fai_disposition` of `ACCEPTED`, otherwise `ERR_NO_QUALIFIED_RUN` (HTTP 422)."
    PRD §3.1: "If no submission of the program is in either granted status, the posture is `BLOCKED`."

    Design: Corner/errors/submission_without_an_accepted_first_article_rejected
    """
    world = X.prototype_world(api)

    # Everything the four higher-ranked filing gates ask for is in place: the
    # design is PROTOTYPE_RELEASED, owned by this program, at its level, with no
    # other package in flight. Only the qualifying run is missing.
    assert world.design["release_status"] == C.RELEASE_PROTOTYPE, (
        f"the design must be submittable, got {world.design['release_status']}"
    )
    _runs, run_meta = validate_paginated(api.list_runs(PROCESS_TECHNICIAN_HEADERS))
    assert run_meta["total_count"] == 0, (
        f"no run has ever been opened for this design, got {run_meta['total_count']}"
    )

    response = api.create_submission(
        F.submission_payload(world.program_id, world.design_id),
        PROGRAM_MANAGER_HEADERS,
    )
    validate_error(response, ERR_NO_QUALIFIED_RUN, 422)

    submissions, meta = validate_paginated(
        api.list_submissions(PROGRAM_MANAGER_HEADERS)
    )
    assert meta["total_count"] == 0, (
        f"the refused filing created no package, got {meta['total_count']}"
    )
    assert submissions == [], "no package exists after a refused filing"

    design = X.refresh_design(api, world.design_id)
    assert design["release_status"] == C.RELEASE_PROTOTYPE, (
        f"a refused filing promotes nothing, got {design['release_status']}"
    )

    program = X.refresh_program(api, world.program_id)
    assert program["delivery_posture"] == C.POSTURE_BLOCKED, (
        f"a program with no granted approval stays blocked, got {program['delivery_posture']}"
    )


def test_heat_treat_charge_above_the_oven_temperature_ceiling_is_refused(api):
    """The oven's rating is checked before any window or capacity arithmetic.

    PRD §3.9: "The requested `target_temp_c` must not exceed the oven's `max_temp_c`, or `ERR_TEMP_EXCEEDS_OVEN` (HTTP 422)."
    PRD §3.9: "The capacity gate comes last."

    Design: Corner/errors/heat_treat_charge_above_the_oven_temperature_ceiling_rejected
    """
    world = X.build_world(api, "complete")
    oven = X.commission_oven(api)

    # The two gates ranked above the temperature check pass: the run is closed
    # out and carries no hold. The two ranked below it would also pass, so the
    # 500 C request is the only thing wrong with this booking.
    assert world.run["process_status"] == C.PROCESS_COMPLETE, (
        f"the run must be schedulable, got {world.run['process_status']}"
    )
    assert world.run["quality_status"] == C.QUALITY_OPEN, (
        f"the run must be off hold, got {world.run['quality_status']}"
    )
    assert oven["max_temp_c"] == 450.0, (
        f"the oven's rating is the ceiling being exceeded, got {oven['max_temp_c']}"
    )
    assert oven["scheduled_load_kg"] == 0.0, (
        f"the oven starts empty, so capacity is not the problem, got {oven['scheduled_load_kg']}"
    )

    response = api.create_batch(
        F.batch_payload(oven["id"], world.run_id, target_temp_c=500.0),
        PROCESS_TECHNICIAN_HEADERS,
    )
    validate_error(response, ERR_TEMP_EXCEEDS_OVEN, 422)

    batches, meta = validate_paginated(api.list_batches(PROCESS_TECHNICIAN_HEADERS))
    assert meta["total_count"] == 0, (
        f"the refused booking created no charge, got {meta['total_count']}"
    )
    assert batches == [], "no charge exists after a refused booking"

    still_empty = X.refresh_oven(api, oven["id"])
    assert still_empty["scheduled_load_kg"] == 0.0, (
        f"the refused booking reserves no oven space, got {still_empty['scheduled_load_kg']}"
    )

    run = X.refresh_run(api, world.run_id)
    assert run["heat_treat_state"] == C.HEAT_TREAT_NOT_STARTED, (
        f"the run's heat treatment never began, got {run['heat_treat_state']}"
    )


def test_third_lot_beyond_the_runs_good_pieces_is_refused(api):
    """Availability is the run's good pieces less every live lot on it, in aggregate.

    PRD §3.11: "Then the quantity gates: `piece_count` must be at least the program's `minimum_order_quantity`, inclusive at the boundary, otherwise `ERR_BELOW_MINIMUM_ORDER_QUANTITY` (HTTP 422); `piece_count` must not exceed the run's `produced_pieces` minus the pieces already carried by lots of this run whose `lot_status` is `ALLOCATED`, `PACKED` or `SHIPPED` — quarantined and returned lots do not consume run availability — otherwise `ERR_RUN_PIECES_EXHAUSTED` (HTTP 422)."

    Design: Corner/errors/third_lot_beyond_the_runs_good_pieces_rejected
    """
    world = X.build_world(api, "approved")
    assert world.run["produced_pieces"] == 25_500, (
        f"the run's good pieces are the ceiling, got {world.run['produced_pieces']}"
    )

    first = X.allocate_lot(api, world.run_id, world.program_id, 20_000)
    second = X.allocate_lot(api, world.run_id, world.program_id, 5_000)
    assert first["lot_status"] == C.LOT_ALLOCATED, (
        f"the first lot must still consume availability, got {first['lot_status']}"
    )
    assert second["lot_status"] == C.LOT_ALLOCATED, (
        f"the second lot must still consume availability, got {second['lot_status']}"
    )

    program = X.refresh_program(api, world.program_id)
    assert program["allocated_pieces"] == 25_000, (
        f"25000 of the run's pieces are spoken for, got {program['allocated_pieces']}"
    )
    # 500 pieces are left on the run, but the commitment is nowhere near spent,
    # so only the run's own availability can refuse a further 1000 pieces.
    assert program["open_commitment_pieces"] == 475_000, (
        f"the commitment is far from exhausted, got {program['open_commitment_pieces']}"
    )
    assert program["minimum_order_quantity"] == 1_000, (
        f"1000 pieces clears the minimum order quantity, got {program['minimum_order_quantity']}"
    )

    response = api.create_lot(
        F.lot_payload(world.run_id, world.program_id, 1_000), PROGRAM_MANAGER_HEADERS
    )
    validate_error(response, ERR_RUN_PIECES_EXHAUSTED, 422)

    # The 500 pieces that are actually left cannot be allocated either, but they
    # fail one rank earlier, on the minimum order quantity.
    remainder = api.create_lot(
        F.lot_payload(world.run_id, world.program_id, 500), PROGRAM_MANAGER_HEADERS
    )
    validate_error(remainder, ERR_BELOW_MINIMUM_ORDER_QUANTITY, 422)

    lots, meta = validate_paginated(api.list_lots(PROGRAM_MANAGER_HEADERS))
    assert meta["total_count"] == 2, (
        f"the two refusals created no lot, got {meta['total_count']}"
    )
    assert {row["id"] for row in lots} == {first["id"], second["id"]}, (
        "the surviving lots are the two that were allocated"
    )

    final = X.refresh_program(api, world.program_id)
    assert final["allocated_pieces"] == 25_000, (
        f"a refused allocation books no pieces, got {final['allocated_pieces']}"
    )
    assert final["open_commitment_pieces"] == 475_000, (
        f"a refused allocation spends no commitment, got {final['open_commitment_pieces']}"
    )
    A.assert_commitment_conserved(final)

    run = X.refresh_run(api, world.run_id)
    assert run["produced_pieces"] == 25_500, (
        f"a refused allocation moves no production count, got {run['produced_pieces']}"
    )


def test_setup_window_entirely_behind_the_clock_is_refused(api, clock):
    """Scheduling is judged against the logical clock, not the wall clock.

    PRD §3.6: "Then `window_end` must be strictly after `window_start`, or `ERR_WINDOW_INVALID` (HTTP 422); and `window_start` must not be earlier than the current reading of the logical clock, or `ERR_WINDOW_IN_PAST` (HTTP 422)."
    PRD §2.5: "Before any request is made the clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real time."

    Design: Corner/errors/setup_window_entirely_behind_the_clock_rejected
    """
    world = X.build_world(api, "machine")

    # Nothing in this world has moved the clock, so it still reads its opening
    # instant and the whole requested window sits behind it.
    assert clock == C.CLOCK_INITIAL, f"the clock must be at its opening reading, got {clock}"
    assert _PAST_WINDOW_END < clock, (
        f"the window must close before the clock reads, got {_PAST_WINDOW_END}"
    )
    # The window is self-consistent, so the inverted-window rank above cannot
    # mask the pastness, and the design, tool and coiler all match.
    assert _PAST_WINDOW_START < _PAST_WINDOW_END, "the window must not be inverted"
    assert world.design["release_status"] == C.RELEASE_PROTOTYPE, (
        f"the design must be bookable, got {world.design['release_status']}"
    )
    assert world.tooling["design_id"] == world.design_id, (
        "the tool must belong to the design being set up"
    )
    assert world.design["wire_diameter_mm"] <= world.machine["max_wire_diameter_mm"], (
        "the wire must fit the coiler, so the diameter rank above cannot fire"
    )

    response = api.create_setup(
        F.setup_payload(
            world.machine_id,
            world.design_id,
            world.tooling_id,
            world.machine_version,
            window_start=_PAST_WINDOW_START,
            window_end=_PAST_WINDOW_END,
        ),
        PROCESS_TECHNICIAN_HEADERS,
    )
    validate_error(response, ERR_WINDOW_IN_PAST, 422)

    setups, meta = validate_paginated(api.list_setups(PROCESS_TECHNICIAN_HEADERS))
    assert meta["total_count"] == 0, (
        f"the refused booking created no setup, got {meta['total_count']}"
    )
    assert setups == [], "no setup exists after a refused booking"

    machine = X.refresh_machine(api, world.machine_id)
    assert machine["machine_state"] == C.MACHINE_IDLE, (
        f"the coiler was never occupied, got {machine['machine_state']}"
    )
    assert machine["active_setup_id"] is None, (
        f"no setup was mounted, got {machine['active_setup_id']}"
    )
    assert machine["version"] == world.machine_version, (
        "a refused booking bumps no coiler version, expected "
        f"{world.machine_version}, got {machine['version']}"
    )


def test_run_whose_wire_demand_exceeds_the_heat_on_hand_is_refused(api):
    """The reservation is sized with the scrap allowance before the heat is asked for it.

    PRD §3.7: "Finally the heat must physically hold enough wire, as computed below; a shortfall answers `ERR_INSUFFICIENT_WIRE` (HTTP 409)."
    PRD §3.7: "Inflate that product by a scrap allowance of three percent — that is, multiply by one plus 0.03."
    PRD §3.7: "That figure is written to the run's `wire_reserved_kg` and is the value compared against the heat's `on_hand_kg` for the sufficiency gate; the heat's ledger is never fed into the computation, only compared against its result."

    Design: Corner/errors/run_whose_wire_demand_exceeds_the_heat_on_hand_rejected
    """
    world = X.build_world(api, "certified_wire")

    # Every gate ranked above the sufficiency check passes: the setup is mounted,
    # the heat is certified on the design's own grade, and the design is released.
    assert world.setup["setup_status"] == C.SETUP_ACTIVE, (
        f"the setup must be mounted, got {world.setup['setup_status']}"
    )
    assert world.wire_lot["certification_status"] == C.CERT_CERTIFIED, (
        f"the heat must be certified, got {world.wire_lot['certification_status']}"
    )
    assert world.wire_lot["material_spec_id"] == world.design["material_spec_id"], (
        "the heat must be on the design's own grade"
    )
    assert world.wire_lot["on_hand_kg"] == 800.0, (
        f"the rack holds 800 kg, got {world.wire_lot['on_hand_kg']}"
    )
    assert world.wire_lot["reserved_kg"] == 0.0, (
        f"nothing is reserved yet, got {world.wire_lot['reserved_kg']}"
    )
    assert world.design["wire_mass_per_piece_kg"] == C.D1_WIRE_MASS_PER_PIECE_KG, (
        f"the stored per-piece mass drives the demand, got {world.design['wire_mass_per_piece_kg']}"
    )

    # 40000 pieces plus the three percent allowance demand more than the rack holds.
    demanded = A.expected_wire_reserved_kg(C.D1_WIRE_MASS_PER_PIECE_KG, 40_000)
    assert demanded > world.wire_lot["on_hand_kg"], (
        f"the demand must exceed the heat, got {demanded}"
    )

    response = api.create_run(
        F.run_payload(
            world.setup_id, world.wire_lot_id, world.design_id, planned_pieces=40_000
        ),
        PROCESS_TECHNICIAN_HEADERS,
    )
    validate_error(response, ERR_INSUFFICIENT_WIRE, 409)

    runs, meta = validate_paginated(api.list_runs(PROCESS_TECHNICIAN_HEADERS))
    assert meta["total_count"] == 0, (
        f"the refused opening created no run, got {meta['total_count']}"
    )
    assert runs == [], "no run exists after a refused opening"

    lot = X.refresh_wire_lot(api, world.wire_lot_id)
    assert lot["on_hand_kg"] == 800.0, (
        f"a refused run takes no wire out of the rack, got {lot['on_hand_kg']}"
    )
    assert lot["reserved_kg"] == 0.0, (
        f"a refused run holds nothing back, got {lot['reserved_kg']}"
    )
    A.assert_wire_ledger_conserved(lot)

    setup = X.refresh_setup(api, world.setup_id)
    assert setup["setup_status"] == C.SETUP_ACTIVE, (
        f"the mounted setup is undisturbed, got {setup['setup_status']}"
    )

    # A plan the heat can actually cover opens on the very same setup and heat,
    # which shows the refusal was about the quantity and nothing else.
    affordable = X.open_run(api, world.setup_id, world.wire_lot_id, world.design_id)
    assert affordable["wire_reserved_kg"] == A.expected_wire_reserved_kg(
        C.D1_WIRE_MASS_PER_PIECE_KG, 26_000
    ), f"the smaller plan reserves what it needs, got {affordable['wire_reserved_kg']}"


def test_allocating_before_the_program_is_priced_is_refused(api):
    """Pieces cannot be allocated without a price to snapshot onto the lot.

    PRD §3.11: "A quote must be on file, that is `quoted_unit_price_cents` must be non-null, otherwise `ERR_PROGRAM_NOT_QUOTED` (HTTP 409)."
    PRD §3.10: "Hop four sets the program's `quote_frozen` to true — the commercial terms are now contractual and no further quote may be run — and re-derives `delivery_posture`, which reaches `ON_TRACK` on a program with no quarantined lots and no held run."

    Design: Corner/errors/lot_create_before_the_program_is_priced_rejected
    """
    # The package is approved without the program ever having been priced, which
    # freezes the quote and makes the refusal permanent for this program.
    world = X.build_world(api, "heat_treated")
    submission = X.file_submission(api, world.program_id, world.design_id)
    X.customer_verdict(
        api, submission["id"], world.program_id, decision=C.DECISION_APPROVE
    )

    run = X.refresh_run(api, world.run_id)
    program = X.refresh_program(api, world.program_id)

    # Every gate ranked above the quote check passes on this world.
    assert run["process_status"] == C.PROCESS_COMPLETE, (
        f"the run must be closed out, got {run['process_status']}"
    )
    assert run["quality_status"] == C.QUALITY_OPEN, (
        f"the run must be off hold, got {run['quality_status']}"
    )
    assert run["heat_treat_state"] == C.HEAT_TREAT_COMPLETE, (
        f"stress relief must be finished, got {run['heat_treat_state']}"
    )
    assert run["peening_verified"] is True, "peening must be honoured on a peened design"
    assert run["min_ppk_observed"] >= program["required_ppk"], (
        f"capability must clear the program floor, got {run['min_ppk_observed']}"
    )
    assert program["delivery_posture"] == C.POSTURE_ON_TRACK, (
        f"the posture must not be blocked, got {program['delivery_posture']}"
    )
    assert program["quoted_unit_price_cents"] is None, (
        f"no price was ever agreed, got {program['quoted_unit_price_cents']}"
    )
    assert program["quote_frozen"] is True, "the approval froze the terms that never existed"

    response = api.create_lot(
        F.lot_payload(world.run_id, world.program_id, 1_000), PROGRAM_MANAGER_HEADERS
    )
    validate_error(response, ERR_PROGRAM_NOT_QUOTED, 409)

    lots, meta = validate_paginated(api.list_lots(PROGRAM_MANAGER_HEADERS))
    assert meta["total_count"] == 0, (
        f"the refused allocation created no lot, got {meta['total_count']}"
    )
    assert lots == [], "no lot exists after a refused allocation"

    final = X.refresh_program(api, world.program_id)
    assert final["quoted_unit_price_cents"] is None, (
        f"the refusal prices nothing, got {final['quoted_unit_price_cents']}"
    )
    assert final["quote_frozen"] is True, "the freeze stands, so the refusal is permanent"
    assert final["delivery_posture"] == C.POSTURE_ON_TRACK, (
        f"the posture is undisturbed, got {final['delivery_posture']}"
    )
    assert final["allocated_pieces"] == 0, (
        f"a refused allocation books no pieces, got {final['allocated_pieces']}"
    )
    A.assert_commitment_conserved(final)


def test_clock_set_to_an_earlier_instant_is_refused(api):
    """The shop clock is monotonic, so no stamped instant can ever be re-dated.

    PRD §2.5: "A `PlantAdmin` advances it by supplying a `to_iso8601` instant to the clock-setting endpoint; the clock is monotonic, so a requested instant earlier than the current reading is rejected with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422) and the clock is left untouched."
    PRD §2.5: "Advancing the clock mutates no entity."

    Design: Corner/errors/clock_set_to_an_earlier_instant_rejected
    """
    program = X.open_program(api)
    X.pin_clock(api, C.CLOCK_SETUP_DAY_START)
    A.assert_audited_resource(program)

    assert _EARLIER_INSTANT < C.CLOCK_SETUP_DAY_START, (
        f"the requested instant must be behind the reading, got {_EARLIER_INSTANT}"
    )

    response = api.set_clock(F.clock_payload(_EARLIER_INSTANT), PLANT_ADMIN_HEADERS)
    validate_error(response, ERR_CLOCK_NOT_MONOTONIC, 422)

    # The clock is left where it was: an equal re-set is legal because the
    # comparison is not strict, which it would not be if the clock had fallen
    # back to the refused instant.
    again = api.set_clock(F.clock_payload(C.CLOCK_SETUP_DAY_START), PLANT_ADMIN_HEADERS)
    validate_success(again, 200)

    # Neither the refusal nor the legal re-set touches a row.
    untouched = X.refresh_program(api, program["id"])
    assert untouched["version"] == program["version"], (
        f"moving the clock bumps no version, expected {program['version']}, got {untouched['version']}"
    )
    assert untouched["updated_at"] == program["updated_at"], (
        f"moving the clock re-stamps nothing, got {untouched['updated_at']}"
    )
    assert untouched["created_at"] == program["created_at"], (
        f"the creation instant is never re-dated, got {untouched['created_at']}"
    )
