"""Which of two simultaneous failures the client is told about, and which gates pass.

Every rejection here is provoked by a request that breaks two rules at once, so a
server that evaluates its checks in any other order answers the wrong error id
while still returning a 4xx. The positive cases are the mirror image: a boundary
value or an unset program flag that must *not* trip the gate next door, proving
each condition is keyed on the field its own rule names. All of them also assert
that the refused write left no row and moved no counter.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as E
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.api_client import ApiClient
from test_helpers.test_users import (
    DESIGN_ENGINEER_HEADERS,
    PROCESS_TECHNICIAN_HEADERS,
    PROGRAM_MANAGER_HEADERS,
    QUALITY_INSPECTOR_HEADERS,
)

_NON_EXISTENT_PROGRAM_ID = "11111111-1111-4111-8111-111111111111"


def test_program_create_unauthenticated_outranks_unauthorized(api: ApiClient) -> None:
    """A header-less request is answered on its headers, not on its role.

    The body names a role that `POST /customer-programs` does not authorise
    either, so both rank 1 and rank 2 are live; the lowest number wins and the
    answer is 401 rather than 403. Nothing is written.

    PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the seven declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else about the request is examined."
    PRD §2.1: "If both headers are well formed but the named role is not among the roles authorised for the requested endpoint in section 4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.8: "When a single request violates more than one rule, exactly one error is returned: the one with the **lowest priority number** in the following ladder."
    PRD §2.8: "1. `ERR_UNAUTHENTICATED` — headers, on every endpoint."
    PRD §2.8: "2. `ERR_UNAUTHORIZED` — role not authorised for the endpoint, on every endpoint."
    PRD §4: "Roles are exhaustive: a role absent from an endpoint's list receives `ERR_UNAUTHORIZED`."
    PRD §2.1: "`DesignEngineer` owns the engineering record — material specifications, spring and wire-form designs, the statistical-process-control plan of critical characteristics, and revisions."

    Design: Corner/validations/program_create_unauthenticated_outranks_unauthorized
    """
    world = X.build_world(api, "program")

    payload = F.program_payload(
        program_code="PGM-2",
        customer_name="Thicket Motorworks",
        application_class=C.CLASS_AUTOMOTIVE_SAFETY,
        ppap_level=3,
        committed_pieces=120_000,
        minimum_order_quantity=2_000,
        amortization_method=C.ACTUAL_BASIS,
    )
    validate_error(api.create_program(payload, {}), E.ERR_UNAUTHENTICATED, 401)

    # A `DesignEngineer` is not authorised for this endpoint either, so the
    # authorization row would also have fired had the headers been present.
    validate_error(
        api.create_program(payload, DESIGN_ENGINEER_HEADERS), E.ERR_UNAUTHORIZED, 403
    )

    programs, meta = validate_paginated(api.list_programs(PROGRAM_MANAGER_HEADERS))
    assert meta["total_count"] == 1
    assert [row["id"] for row in programs] == [world.program_id]
    assert programs[0]["program_code"] == C.CANONICAL_PROGRAM_CODE


def test_submission_review_by_a_design_engineer_returns_unauthorized_before_the_ownership_gate(
    api: ApiClient,
) -> None:
    """The ownership comparison is defined only for the customer role.

    Rank 2 therefore answers a `DesignEngineer` verdict attempt before rank 3 can
    ask which program an engineering user id belongs to, and none of the four
    cascade hops of a real `APPROVE` fires.

    PRD §2.1: "If both headers are well formed but the named role is not among the roles authorised for the requested endpoint in section 4, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "`CustomerRepresentative` is the buying organisation acting as itself and is the sole holder of the production-part approval verdict."
    PRD §2.1: "When `X-User-Role` is `DesignEngineer`, `EngineeringManager`, `ProcessTechnician`, `QualityInspector`, `ProgramManager` or `PlantAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity."
    PRD §3.10: "The verdict belongs to the `CustomerRepresentative` alone, and only for its own program: because that role is entity-backed, its `X-User-ID` must equal the submission's `program_id` or the request is refused with `ERR_PROGRAM_OWNERSHIP_MISMATCH`."
    PRD §2.8: "When a single request violates more than one rule, exactly one error is returned: the one with the **lowest priority number** in the following ladder."
    PRD §2.8: "2. `ERR_UNAUTHORIZED` — role not authorised for the endpoint, on every endpoint."
    PRD §2.8: "3. `ERR_PROGRAM_OWNERSHIP_MISMATCH` — customer-representative ownership, on every endpoint a `CustomerRepresentative` may call."
    PRD §4: "Roles are exhaustive: a role absent from an endpoint's list receives `ERR_UNAUTHORIZED`."
    PRD §3.10: "Hop one sets `submission_status` to `APPROVED`, a terminal status."
    PRD §3.10: "Hop two promotes the design `PROTOTYPE_RELEASED → PRODUCTION_RELEASED`."
    PRD §3.10: "Hop four sets the program's `quote_frozen` to true — the commercial terms are now contractual and no further quote may be run — and re-derives `delivery_posture`, which reaches `ON_TRACK` on a program with no quarantined lots and no held run."

    Design: Corner/validations/submission_review_by_a_design_engineer_returns_unauthorized_before_the_ownership_gate
    """
    world = X.build_world(api, "submitted")
    assert world.submission["submission_status"] == C.SUBMISSION_SUBMITTED

    validate_error(
        api.review_submission(
            world.submission_id,
            {"decision": C.DECISION_APPROVE},
            DESIGN_ENGINEER_HEADERS,
        ),
        E.ERR_UNAUTHORIZED,
        403,
    )

    submission = X.refresh_submission(api, world.submission_id)
    assert submission["submission_status"] == C.SUBMISSION_SUBMITTED
    assert submission["reviewed_by_program_id"] is None
    assert submission["decided_at"] is None

    design = X.refresh_design(api, world.design_id)
    assert design["release_status"] == C.RELEASE_PROTOTYPE

    program = X.refresh_program(api, world.program_id)
    assert program["quote_frozen"] is False


def test_design_create_invalid_request_outranks_the_program_existence_lookup(
    api: ApiClient,
) -> None:
    """Body shape is judged before any foreign key is dereferenced.

    The payload carries an undeclared `form_type` member and a `program_id` that
    resolves to nothing, so rank 4 answers 400 and the client is never told about
    the missing program at rank 6.

    PRD §3.2: "The form family is declared as `form_type`, one of `COMPRESSION`, `EXTENSION` or `TORSION`, and the end configuration as `end_type`, one of `CLOSED_GROUND`, `CLOSED_UNGROUND`, `OPEN`, `HOOK_EXTENSION` or `TORSION_LEG`."
    PRD §2.8: "Foreign keys carried in a request body are resolved after the path but before any business rule reads them."
    PRD §2.8: "When a single request violates more than one rule, exactly one error is returned: the one with the **lowest priority number** in the following ladder."
    PRD §2.8: "4. `ERR_INVALID_REQUEST` — body shape, required fields, enum membership, numeric constraints and measurement typing, on every endpoint."
    PRD §2.8: "6. `ERR_PROGRAM_NOT_FOUND` — on `GET`/`POST /customer-programs/{id}/*`, `POST /spring-designs`, `POST /qualification-submissions`, `POST /shipment-lots`."

    Design: Corner/validations/design_create_invalid_request_outranks_the_program_existence_lookup
    """
    world = X.build_world(api, "material")

    payload = F.design_payload(
        _NON_EXISTENT_PROGRAM_ID,
        world.material_id,
        form_type="SPIRAL_TAPER",
    )
    validate_error(
        api.create_design(payload, DESIGN_ENGINEER_HEADERS), E.ERR_INVALID_REQUEST, 400
    )

    designs, meta = validate_paginated(api.list_designs(DESIGN_ENGINEER_HEADERS))
    assert meta["total_count"] == 0
    assert designs == []

    # The same body with a declared form family would have reached the lookup.
    validate_error(
        api.create_design(
            F.design_payload(_NON_EXISTENT_PROGRAM_ID, world.material_id),
            DESIGN_ENGINEER_HEADERS,
        ),
        E.ERR_PROGRAM_NOT_FOUND,
        404,
    )


def test_program_posture_blocked_is_shadowed_by_ppap_not_approved_on_lot_creation(
    api: ApiClient,
) -> None:
    """The posture row can never answer first on this endpoint.

    A `BLOCKED` posture means no submission is in a granted status, which is the
    very condition the earlier PPAP row tests from the design side, so allocation
    against a quoted but unapproved program answers rank 41 and rank 44 stays
    unreachable here.

    PRD §3.11: "The PPAP standing gate requires both that the design's `release_status` is `PROTOTYPE_RELEASED` or `PRODUCTION_RELEASED` **and** that the newest qualification submission by `created_at` for the program and the run's design has a `submission_status` of `APPROVED` or `INTERIM_APPROVED`; a failure answers `ERR_PPAP_NOT_APPROVED` (HTTP 422)."
    PRD §3.11: "The program's `delivery_posture` must not be `BLOCKED`, which answers `ERR_PROGRAM_POSTURE_BLOCKED` (HTTP 409); as section 2.8 explains, on this endpoint that row is structurally shadowed by the PPAP gate."
    PRD §2.8: "When a single request violates more than one rule, exactly one error is returned: the one with the **lowest priority number** in the following ladder."
    PRD §2.8: "41. `ERR_PPAP_NOT_APPROVED` — on `POST /machine-setups`, `POST /production-runs`, `POST /shipment-lots`."
    PRD §2.8: "44. `ERR_PROGRAM_POSTURE_BLOCKED` — on `POST /shipment-lots`, `POST /shipment-lots/{id}/ship`."
    PRD §2.8: "And on lot allocation, rank 44 is structurally shadowed by rank 41 — a program whose posture is `BLOCKED` has no granted approval on file, so rank 41 answers first — which means `ERR_PROGRAM_POSTURE_BLOCKED` surfaces in practice on the shipping operation, where an already packed lot is presented after a resubmission dropped the program's posture back to `BLOCKED`."
    PRD §3.1: "If no submission of the program is in either granted status, the posture is `BLOCKED`."
    PRD §3.1: "`delivery_posture` starts at `BLOCKED`, which is simply what the posture rule below returns for a program with no granted approval on file."
    PRD §3.1: "A freshly opened program starts its commitment ledger at rest: `open_commitment_pieces` is initialised to the same number as `committed_pieces`, while `allocated_pieces`, `shipped_pieces` and `quarantined_lot_count` all start at 0."

    Design: Corner/validations/program_posture_blocked_is_shadowed_by_ppap_not_approved_on_lot_creation
    """
    world = X.build_world(api, "quoted")
    assert world.design["release_status"] == C.RELEASE_PROTOTYPE
    assert world.program["delivery_posture"] == A.expected_delivery_posture(
        False, 0, False
    )
    assert world.program["delivery_posture"] == C.POSTURE_BLOCKED

    submissions, submission_meta = validate_paginated(
        api.list_submissions(PROGRAM_MANAGER_HEADERS)
    )
    assert submission_meta["total_count"] == 0, "no package has been filed at all"
    assert submissions == []

    validate_error(
        api.create_lot(
            F.lot_payload(world.run_id, world.program_id, 1_000),
            PROGRAM_MANAGER_HEADERS,
        ),
        E.ERR_PPAP_NOT_APPROVED,
        422,
    )

    lots, lot_meta = validate_paginated(api.list_lots(PROGRAM_MANAGER_HEADERS))
    assert lot_meta["total_count"] == 0
    assert lots == []

    program = X.refresh_program(api, world.program_id)
    assert program["delivery_posture"] == C.POSTURE_BLOCKED
    assert program["allocated_pieces"] == 0
    assert program["open_commitment_pieces"] == 500_000
    assert program["committed_pieces"] == 500_000
    A.assert_commitment_conserved(program)


def test_characteristic_design_mismatch_outranks_the_subgroup_size_floor_on_inspections(
    api: ApiClient,
) -> None:
    """A referential failure is reported before a shape failure on the same body.

    The subgroup is both attached to a foreign design's characteristic and one
    measurement short of the three-value floor, so rank 51 answers and the
    cross-design measurement cannot hide behind the subgroup-size complaint.

    PRD §3.8: "The characteristic must belong to the run's design, otherwise `ERR_CHARACTERISTIC_DESIGN_MISMATCH`, and the subgroup must again carry at least three measurements, otherwise `ERR_INVALID_SUBGROUP_SIZE`."
    PRD §2.8: "When a single request violates more than one rule, exactly one error is returned: the one with the **lowest priority number** in the following ladder."
    PRD §2.8: "51. `ERR_CHARACTERISTIC_DESIGN_MISMATCH` — on `POST /production-runs/{id}/fai`, `POST /production-runs/{id}/inspections`."
    PRD §2.8: "54. `ERR_INVALID_SUBGROUP_SIZE` — on `POST /production-runs/{id}/fai`, `POST /production-runs/{id}/inspections`."
    PRD §3.7: "At the run level, `min_cpk_observed` is refreshed to the lowest `cpk_value` across all of the run's inspection records, while `min_ppk_observed` is refreshed to the lowest `ppk_value` across only those of the run's records whose `record_kind` is `SPC` and whose characteristic has `is_safety_critical` true."

    Design: Corner/validations/characteristic_design_mismatch_outranks_the_subgroup_size_floor_on_inspections
    """
    world = X.build_world(api, "running")
    assert world.run["min_cpk_observed"] == 3.333

    foreign_design = X.draft_design(
        api, world.program_id, world.material_id, part_number="D2"
    )
    foreign_characteristic = X.add_characteristic(api, foreign_design["id"])

    validate_error(
        api.record_inspection(
            world.run_id,
            F.measurement_payload(foreign_characteristic["id"], [59.95, 60.0]),
            QUALITY_INSPECTOR_HEADERS,
        ),
        E.ERR_CHARACTERISTIC_DESIGN_MISMATCH,
        422,
    )

    records, meta = validate_paginated(
        api.list_inspection_records(
            QUALITY_INSPECTOR_HEADERS,
            {"characteristic_id": foreign_characteristic["id"]},
        )
    )
    assert meta["total_count"] == 0
    assert records == []

    run = X.refresh_run(api, world.run_id)
    assert run["min_cpk_observed"] == 3.333
    assert run["quality_status"] == C.QUALITY_OPEN


def test_corrosion_requirement_unmet_outranks_the_biocompatibility_gate(
    api: ApiClient,
) -> None:
    """One material can fail both metallurgical gates, and corrosion answers.

    The wire is rated at 48 salt-spray hours against a 96-hour program floor and
    is also not biocompatible against a program that demands biocompatibility, so
    rank 35 answers rather than rank 36.

    PRD §3.2: "Two metallurgical gates are checked against the owning program before any of this is persisted."
    PRD §3.2: "The chosen material's `salt_spray_hours` must be at least the program's `required_salt_spray_hours`; a shortfall is rejected with `ERR_CORROSION_REQUIREMENT_UNMET` (HTTP 422)."
    PRD §3.2: "And if the program's `biocompatibility_required` is true, the material's `biocompatible` must also be true; otherwise the answer is `ERR_BIOCOMPATIBILITY_REQUIRED` (HTTP 422)."
    PRD §2.8: "When a single request violates more than one rule, exactly one error is returned: the one with the **lowest priority number** in the following ladder."
    PRD §2.8: "35. `ERR_CORROSION_REQUIREMENT_UNMET` — on `POST /spring-designs`, `POST /spring-designs/{id}/revisions`."
    PRD §2.8: "36. `ERR_BIOCOMPATIBILITY_REQUIRED` — on `POST /spring-designs`, `POST /spring-designs/{id}/revisions`."
    PRD §3.1: "The corrosion story is carried by `coating`, one of `NONE`, `ZINC_PHOSPHATE`, `PASSIVATED`, `ELECTROPOLISHED` or `PTFE`, and `salt_spray_hours`, the coating's endurance in hours, which must be at least 0."
    PRD §3.1: "`biocompatible` records whether the grade plus coating is qualified for implant or device contact and defaults to false."

    Design: Corner/validations/corrosion_requirement_unmet_outranks_the_biocompatibility_gate
    """
    program = X.open_program(
        api,
        program_code="PGM-MED",
        application_class=C.CLASS_MEDICAL_IMPLANT,
        required_salt_spray_hours=96,
        biocompatibility_required=True,
    )
    assert program["required_salt_spray_hours"] == 96
    assert program["biocompatibility_required"] is True

    bare = X.register_material(
        api,
        spec_code="MS-PLAIN",
        coating=C.COATING_NONE,
        salt_spray_hours=48,
        biocompatible=False,
    )
    assert bare["salt_spray_hours"] < program["required_salt_spray_hours"]
    assert bare["biocompatible"] is False

    validate_error(
        api.create_design(
            F.design_payload(program["id"], bare["id"]), DESIGN_ENGINEER_HEADERS
        ),
        E.ERR_CORROSION_REQUIREMENT_UNMET,
        422,
    )

    designs, meta = validate_paginated(api.list_designs(DESIGN_ENGINEER_HEADERS))
    assert meta["total_count"] == 0
    assert designs == []

    # Repair only the corrosion rating and the second gate answers, which is what
    # proves it was live on the first request too.
    coated = X.register_material(
        api,
        spec_code="MS-COATED",
        coating=C.COATING_ZINC_PHOSPHATE,
        salt_spray_hours=96,
        biocompatible=False,
    )
    validate_error(
        api.create_design(
            F.design_payload(program["id"], coated["id"], part_number="D2"),
            DESIGN_ENGINEER_HEADERS,
        ),
        E.ERR_BIOCOMPATIBILITY_REQUIRED,
        422,
    )
    _, meta = validate_paginated(api.list_designs(DESIGN_ENGINEER_HEADERS))
    assert meta["total_count"] == 0


def test_biocompatibility_gate_passes_when_the_program_does_not_demand_it(
    api: ApiClient,
) -> None:
    """The gate is keyed on the program's flag, not on the material alone.

    The identical non-biocompatible chrome-silicon wire that an implant program
    must refuse is accepted verbatim by an industrial program whose flag is false,
    and the full engineering stack runs on it.

    PRD §3.2: "And if the program's `biocompatibility_required` is true, the material's `biocompatible` must also be true; otherwise the answer is `ERR_BIOCOMPATIBILITY_REQUIRED` (HTTP 422)."
    PRD §3.1: "`biocompatible` records whether the grade plus coating is qualified for implant or device contact and defaults to false."
    PRD §3.2: "On acceptance the server stamps `created_by_user_id` with the incoming `X-User-ID`, leaves `reviewed_by_user_id` null, sets `current_revision_no` to 1 with `superseded_revision_no` null, sets `release_status` to `DRAFT`, and then runs the complete engineering stack."
    PRD §3.2: "The value written to `spring_rate_n_per_mm` is that megapascal shear modulus multiplied by the wire diameter raised to the fourth power, divided by the product of eight, the mean coil diameter cubed, and the active coil count, with the result rounded half up to three decimal places."
    PRD §3.2: "Which one binds is decided by the owning program's `application_class`: the design's `fatigue_criterion` is set to `SODERBERG` when the class is `AUTOMOTIVE_SAFETY` or `MEDICAL_IMPLANT`, and to `GOODMAN` for `AUTOMOTIVE_NON_SAFETY`, `MEDICAL_DEVICE` or `INDUSTRIAL`."
    PRD §3.2: "`fatigue_margin_ratio` is then one divided by the denominator belonging to the criterion in force, rounded half up to three decimal places."

    Design: Corner/validations/biocompatibility_gate_passes_when_the_program_does_not_demand_it
    """
    implant = X.open_program(
        api,
        program_code="PGM-MED",
        application_class=C.CLASS_MEDICAL_IMPLANT,
        biocompatibility_required=True,
    )
    industrial = X.open_program(
        api,
        application_class=C.CLASS_INDUSTRIAL,
        biocompatibility_required=False,
    )
    assert industrial["biocompatibility_required"] is False

    material = X.register_material(api)
    assert material["biocompatible"] is False
    assert material["salt_spray_hours"] == 96

    data = validate_success(
        api.create_design(
            F.design_payload(industrial["id"], material["id"]), DESIGN_ENGINEER_HEADERS
        ),
        201,
    )
    assert data["release_status"] == C.RELEASE_DRAFT

    rate = A.expected_spring_rate(79.3, 2.5, 20.0, 8)
    assert rate == 9.031
    assert data["spring_rate_n_per_mm"] == rate
    A.assert_decimal_places(data["spring_rate_n_per_mm"], 3, "spring_rate_n_per_mm")

    criterion = A.expected_fatigue_criterion(C.CLASS_INDUSTRIAL)
    assert criterion == "GOODMAN"
    assert data["fatigue_criterion"] == criterion

    margin = A.expected_fatigue_margin(
        C.CLASS_INDUSTRIAL, 2.5, 20.0, 150, 50, 1900, True
    )
    assert margin == 1.757
    assert data["fatigue_margin_ratio"] == margin
    A.assert_decimal_places(data["fatigue_margin_ratio"], 3, "fatigue_margin_ratio")

    # The same body under the implant program is refused on the material's flag.
    validate_error(
        api.create_design(
            F.design_payload(implant["id"], material["id"], part_number="D2"),
            DESIGN_ENGINEER_HEADERS,
        ),
        E.ERR_BIOCOMPATIBILITY_REQUIRED,
        422,
    )


def test_corrosion_gate_passes_at_exactly_the_required_salt_spray_hours(
    api: ApiClient,
) -> None:
    """The comparison is at-least, so equality is admitted.

    A coating rated at exactly the program's floor of 96 hours creates the design,
    while a rating one hour short of it is refused.

    PRD §3.2: "The chosen material's `salt_spray_hours` must be at least the program's `required_salt_spray_hours`; a shortfall is rejected with `ERR_CORROSION_REQUIREMENT_UNMET` (HTTP 422)."
    PRD §3.1: "The corrosion story is carried by `coating`, one of `NONE`, `ZINC_PHOSPHATE`, `PASSIVATED`, `ELECTROPOLISHED` or `PTFE`, and `salt_spray_hours`, the coating's endurance in hours, which must be at least 0."
    PRD §3.2: "`wire_mass_per_piece_kg` is then the developed length converted from millimetres to metres by dividing by one thousand, multiplied by that area, multiplied by the material's `density_kg_per_m3`, rounded half up to exactly six decimal places."
    PRD §3.2: "`tangle_risk_class` is `HIGH` when that index is at least 4.000 **or** the `end_type` is `HOOK_EXTENSION`, and `LOW` in every other case."

    Design: Corner/validations/corrosion_gate_passes_at_exactly_the_required_salt_spray_hours
    """
    program = X.open_program(api, required_salt_spray_hours=96)
    material = X.register_material(api, salt_spray_hours=96)
    assert material["salt_spray_hours"] == program["required_salt_spray_hours"]

    data = validate_success(
        api.create_design(
            F.design_payload(program["id"], material["id"]), DESIGN_ENGINEER_HEADERS
        ),
        201,
    )
    assert data["part_number"] == C.CANONICAL_PART_NUMBER == "D1"

    tangle_class = A.expected_tangle_risk_class(60.0, 20.0, C.END_CLOSED_GROUND)
    assert tangle_class == C.TANGLE_LOW == "LOW"
    assert data["tangle_risk_class"] == tangle_class

    mass = A.expected_wire_mass_per_piece_kg(2.5, 20.0, 8, C.END_CLOSED_GROUND, 7850)
    assert mass == 0.021185
    assert data["wire_mass_per_piece_kg"] == mass
    A.assert_decimal_places(data["wire_mass_per_piece_kg"], 6, "wire_mass_per_piece_kg")

    # One hour short of the same floor is refused, so the pass was on equality.
    shy = X.register_material(api, spec_code="MS-SHY", salt_spray_hours=95)
    validate_error(
        api.create_design(
            F.design_payload(program["id"], shy["id"], part_number="D2"),
            DESIGN_ENGINEER_HEADERS,
        ),
        E.ERR_CORROSION_REQUIREMENT_UNMET,
        422,
    )


def test_heat_treat_gate_requires_verified_peening_and_not_merely_a_complete_batch(
    api: ApiClient,
) -> None:
    """The gate is a conjunction, not a state check on the batch alone.

    The batch ran to `COMPLETE` and set the run's `heat_treat_state` to `COMPLETE`,
    but the technician reported that peening did not happen on a design that
    requires it, so `peening_verified` stayed false and allocation is still
    refused. The unpeened discharge also puts the run on a hold, which is lifted
    first so that the heat-treat row is the only condition left failing.

    PRD §3.11: "Heat treatment must be finished and peening honoured: the run's `heat_treat_state` must be `COMPLETE`, and either the design does not require shot peening or the run's `peening_verified` is true, otherwise `ERR_HEAT_TREAT_INCOMPLETE` (HTTP 422)."
    PRD §3.9: "Discharge removes the batch's `load_kg` from the oven's `scheduled_load_kg`, sets the run's `heat_treat_state` to `COMPLETE`, and sets the run's `peening_verified` to true only when `peening_performed` is true."
    PRD §3.9: "Then comes the trap: **if the design requires shot peening and the batch reports that peening was not performed**, that is, `shot_peening_required` on the design is true while `peening_performed` on the batch is false, the run's `quality_status` transitions `OPEN → SPC_HOLD` and the same cascade as an out-of-control safety-critical subgroup fires — the run's `ALLOCATED` and `PACKED` lots are quarantined with `quarantine_reason` `SPC_HOLD_CASCADE`, each affected program's `quarantined_lot_count`, `allocated_pieces` and `open_commitment_pieces` are adjusted, and each affected `delivery_posture` is re-derived."
    PRD §3.9: "A part whose endurance limit was calculated with the peened factor cannot be shipped unpeened."
    PRD §3.8: "Lifting a hold is a `QualityInspector`'s judgement, delivered as a `decision` of `RELEASE`, `ACCEPT_AS_IS` or `SCRAP`."
    PRD §3.8: "`RELEASE` returns the run `SPC_HOLD → OPEN` and is the cyclic edge on the quality axis — a run can be held and released repeatedly over its life."
    PRD §3.11: "The run's `process_status` must be `COMPLETE`, otherwise `ERR_RUN_NOT_COMPLETE` (HTTP 409); its `quality_status` must be `OPEN` or `DISPOSITIONED_ACCEPT`, and a held or scrapped run answers `ERR_RUN_ON_SPC_HOLD` (HTTP 409)."
    PRD §2.8: "42. `ERR_HEAT_TREAT_INCOMPLETE` — on `POST /shipment-lots`."

    Design: Corner/validations/heat_treat_gate_requires_verified_peening_and_not_merely_a_complete_batch
    """
    world = X.build_world(api, "approved", peening_performed=False)
    assert world.design["shot_peening_required"] is True
    assert world.batch["peening_requested"] is True
    assert world.batch["peening_performed"] is False

    run = X.refresh_run(api, world.run_id)
    assert run["heat_treat_state"] == C.HEAT_TREAT_COMPLETE
    assert run["peening_verified"] is False
    assert run["process_status"] == C.PROCESS_COMPLETE
    assert run["quality_status"] == C.QUALITY_SPC_HOLD

    # Lift the run-level hold the unpeened discharge raised, so the only gate
    # still failing on the allocation is the heat-treat conjunction.
    validate_success(
        api.quality_disposition(
            world.run_id,
            {"decision": C.DECISION_RELEASE},
            QUALITY_INSPECTOR_HEADERS,
        )
    )
    run = X.refresh_run(api, world.run_id)
    assert run["quality_status"] == C.QUALITY_OPEN
    assert run["heat_treat_state"] == C.HEAT_TREAT_COMPLETE
    assert run["peening_verified"] is False

    validate_error(
        api.create_lot(
            F.lot_payload(world.run_id, world.program_id, 1_000),
            PROGRAM_MANAGER_HEADERS,
        ),
        E.ERR_HEAT_TREAT_INCOMPLETE,
        422,
    )

    run = X.refresh_run(api, world.run_id)
    assert run["heat_treat_state"] == C.HEAT_TREAT_COMPLETE
    assert run["peening_verified"] is False

    lots, meta = validate_paginated(api.list_lots(PROGRAM_MANAGER_HEADERS))
    assert meta["total_count"] == 0
    assert lots == []

    program = X.refresh_program(api, world.program_id)
    assert program["allocated_pieces"] == 0
    assert program["open_commitment_pieces"] == 500_000
    A.assert_commitment_conserved(program)


def test_heat_treat_gate_outranks_the_program_ppk_floor_on_lot_creation(
    api: ApiClient,
) -> None:
    """Two process gates fail at once and the heat-treat row answers.

    The run was never heat treated and its worst safety-critical subgroup left a
    0.833 long-run capability against a 1.000 program floor, so rank 42 and rank
    43 are both live and the client is told about the oven, not the statistics.

    PRD §3.11: "Heat treatment must be finished and peening honoured: the run's `heat_treat_state` must be `COMPLETE`, and either the design does not require shot peening or the run's `peening_verified` is true, otherwise `ERR_HEAT_TREAT_INCOMPLETE` (HTTP 422)."
    PRD §3.11: "The run's `min_ppk_observed` must be non-null and at least the program's `required_ppk`, otherwise `ERR_PPK_BELOW_PROGRAM_FLOOR` (HTTP 422) — a run that has never taken a safety-critical SPC subgroup has a null `min_ppk_observed` and fails here."
    PRD §2.8: "When a single request violates more than one rule, exactly one error is returned: the one with the **lowest priority number** in the following ladder."
    PRD §2.8: "42. `ERR_HEAT_TREAT_INCOMPLETE` — on `POST /shipment-lots`."
    PRD §2.8: "43. `ERR_PPK_BELOW_PROGRAM_FLOOR` — on `POST /shipment-lots`."
    PRD §3.7: "`cpk_value` is the short-run capability of this subgroup: take the characteristic's `usl` minus the unrounded mean, and the unrounded mean minus the characteristic's `lsl`, keep whichever of those two distances is **smaller**, divide it by three times the unrounded standard deviation, and round half up to three decimal places."
    PRD §3.7: "From that pooled sample take the pooled mean, form the same two distances against `usl` and `lsl`, keep the smaller, divide by three times the pooled standard deviation, and round half up to three decimal places."
    PRD §3.7: "Each record keeps the pooled figure it was stamped with at its own creation — earlier rows are never restamped when a later subgroup arrives."
    PRD §3.7: "At the run level, `min_cpk_observed` is refreshed to the lowest `cpk_value` across all of the run's inspection records, while `min_ppk_observed` is refreshed to the lowest `ppk_value` across only those of the run's records whose `record_kind` is `SPC` and whose characteristic has `is_safety_critical` true."
    PRD §3.8: "`RELEASE` returns the run `SPC_HOLD → OPEN` and is the cyclic edge on the quality axis — a run can be held and released repeatedly over its life."

    Design: Corner/validations/heat_treat_gate_outranks_the_program_ppk_floor_on_lot_creation
    """
    world = X.build_world(api, "running")
    characteristic = world.characteristics[0]
    assert characteristic["is_safety_critical"] is True
    assert world.program["required_ppk"] == 1.0

    weak = X.record_spc_subgroup(
        api, world.run_id, characteristic, [59.8, 60.0, 60.2]
    )
    expected_cpk = A.expected_cpk_value([59.8, 60.0, 60.2], 59.5, 60.5)
    expected_ppk = A.expected_ppk_value([59.8, 60.0, 60.2], 59.5, 60.5)
    assert expected_cpk == 0.833
    assert expected_ppk == 0.833
    assert weak["cpk_value"] == expected_cpk
    assert weak["ppk_value"] == expected_ppk
    A.assert_decimal_places(weak["cpk_value"], 3, "cpk_value")
    A.assert_decimal_places(weak["ppk_value"], 3, "ppk_value")
    assert weak["control_state"] == A.expected_control_state(
        [59.8, 60.0, 60.2], 59.5, 60.5, characteristic["cpk_floor"]
    )
    assert weak["control_state"] == C.CONTROL_OUT_OF_CONTROL

    # A recovered subgroup lets the hold be lifted, and its own pooled figure is
    # above the floor, but the weaker stamped row keeps the run minimum at 0.833.
    recovered = X.record_spc_subgroup(
        api, world.run_id, characteristic, C.IN_CONTROL_SUBGROUP
    )
    pooled = A.expected_ppk_value(
        [59.8, 60.0, 60.2] + list(C.IN_CONTROL_SUBGROUP), 59.5, 60.5
    )
    assert pooled == 1.278
    assert recovered["ppk_value"] == pooled

    validate_success(
        api.quality_disposition(
            world.run_id,
            {"decision": C.DECISION_RELEASE},
            QUALITY_INSPECTOR_HEADERS,
        )
    )

    X.complete_run(api, world.run_id)
    run = X.refresh_run(api, world.run_id)
    assert run["min_cpk_observed"] == 0.833
    assert run["min_ppk_observed"] == 0.833
    assert run["heat_treat_state"] == C.HEAT_TREAT_NOT_STARTED

    program = X.refresh_program(api, world.program_id)
    X.price_program(api, program, world.design_id, quoted_qty=26_000)
    submission = X.file_submission(api, world.program_id, world.design_id)
    X.customer_verdict(api, submission["id"], world.program_id)

    validate_error(
        api.create_lot(
            F.lot_payload(world.run_id, world.program_id, 1_000),
            PROGRAM_MANAGER_HEADERS,
        ),
        E.ERR_HEAT_TREAT_INCOMPLETE,
        422,
    )

    run = X.refresh_run(api, world.run_id)
    assert run["min_ppk_observed"] == 0.833
    assert run["min_cpk_observed"] == 0.833
    assert run["min_ppk_observed"] < world.program["required_ppk"]
    assert run["heat_treat_state"] == C.HEAT_TREAT_NOT_STARTED

    lots, meta = validate_paginated(api.list_lots(PROGRAM_MANAGER_HEADERS))
    assert meta["total_count"] == 0
    assert lots == []


def test_window_invalid_outranks_window_in_past_on_setup_creation(
    api: ApiClient,
) -> None:
    """An inverted window is reported before a stale one.

    The booking's end precedes its start and the whole span sits two days behind
    the logical clock's opening reading, so rank 65 answers and rank 66 never
    speaks. The rejected booking bumps nothing on the coiler.

    PRD §3.6: "Then `window_end` must be strictly after `window_start`, or `ERR_WINDOW_INVALID` (HTTP 422); and `window_start` must not be earlier than the current reading of the logical clock, or `ERR_WINDOW_IN_PAST` (HTTP 422)."
    PRD §2.5: "Before any request is made the clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real time."
    PRD §2.8: "When a single request violates more than one rule, exactly one error is returned: the one with the **lowest priority number** in the following ladder."
    PRD §2.8: "65. `ERR_WINDOW_INVALID` — on `POST /machine-setups`, `POST /heat-treat-batches`."
    PRD §2.8: "66. `ERR_WINDOW_IN_PAST` — on `POST /machine-setups`, `POST /heat-treat-batches`."
    PRD §3.6: "On success the coiler transitions `IDLE → SETUP`, its `active_setup_id` is set to this setup's id, and its `version` increases by 1."

    Design: Corner/validations/window_invalid_outranks_window_in_past_on_setup_creation
    """
    world = X.build_world(api, "machine")
    machine_version = world.machine["version"]
    assert world.machine["machine_state"] == "IDLE"

    inverted_start = "2026-07-30T12:00:00Z"
    inverted_end = "2026-07-30T08:00:00Z"
    assert inverted_end < inverted_start, "the window is inverted"
    assert inverted_start < C.CLOCK_INITIAL, "and it is entirely behind the clock"

    validate_error(
        api.create_setup(
            F.setup_payload(
                world.machine_id,
                world.design_id,
                world.tooling_id,
                machine_version,
                window_start=inverted_start,
                window_end=inverted_end,
            ),
            PROCESS_TECHNICIAN_HEADERS,
        ),
        E.ERR_WINDOW_INVALID,
        422,
    )

    setups, meta = validate_paginated(api.list_setups(PROCESS_TECHNICIAN_HEADERS))
    assert meta["total_count"] == 0
    assert setups == []

    machine = X.refresh_machine(api, world.machine_id)
    assert machine["version"] == machine_version
    assert machine["machine_state"] == "IDLE"
    assert machine["active_setup_id"] is None


def test_material_mismatch_outranks_the_wire_sufficiency_check_on_run_creation(
    api: ApiClient,
) -> None:
    """The heat's identity is checked before its mass.

    The named heat belongs to a different material specification and holds one
    kilogram against a demand of 872.822, so rank 48 answers and the sufficiency
    arithmetic at rank 72 is never reached; the heat's ledger does not move.

    PRD §3.7: "The heat's `material_spec_id` must equal the design's `material_spec_id`, or the answer is `ERR_MATERIAL_MISMATCH` (HTTP 422)."
    PRD §3.7: "Finally the heat must physically hold enough wire, as computed below; a shortfall answers `ERR_INSUFFICIENT_WIRE` (HTTP 409)."
    PRD §2.8: "When a single request violates more than one rule, exactly one error is returned: the one with the **lowest priority number** in the following ladder."
    PRD §2.8: "48. `ERR_MATERIAL_MISMATCH` — on `POST /production-runs`."
    PRD §2.8: "72. `ERR_INSUFFICIENT_WIRE` — on `POST /production-runs`."
    PRD §3.7: "Start from the design's **stored** `wire_mass_per_piece_kg`, already rounded to six decimal places."
    PRD §3.7: "That figure is written to the run's `wire_reserved_kg` and is the value compared against the heat's `on_hand_kg` for the sufficiency gate; the heat's ledger is never fed into the computation, only compared against its result."
    PRD §3.7: "On success the reservation moves mass without creating any: `wire_reserved_kg` is subtracted from the heat's `on_hand_kg` and added to its `reserved_kg`, leaving `received_kg` untouched."

    Design: Corner/validations/material_mismatch_outranks_the_wire_sufficiency_check_on_run_creation
    """
    world = X.build_world(api, "active_setup")
    assert world.setup["setup_status"] == C.SETUP_ACTIVE

    other_material = X.register_material(api, spec_code="MS-2")
    assert other_material["id"] != world.design["material_spec_id"]

    light_heat = X.certified_wire(
        api, other_material["id"], heat_number="HT-2", received_kg=1.0
    )
    assert light_heat["material_spec_id"] == other_material["id"]
    assert light_heat["on_hand_kg"] == 1.0

    demand = A.expected_wire_reserved_kg(world.design["wire_mass_per_piece_kg"], 40_000)
    assert demand == 872.822
    assert demand > light_heat["on_hand_kg"], "the sufficiency gate is live as well"

    validate_error(
        api.create_run(
            F.run_payload(
                world.setup_id,
                light_heat["id"],
                world.design_id,
                planned_pieces=40_000,
            ),
            PROCESS_TECHNICIAN_HEADERS,
        ),
        E.ERR_MATERIAL_MISMATCH,
        422,
    )

    runs, meta = validate_paginated(api.list_runs(PROCESS_TECHNICIAN_HEADERS))
    assert meta["total_count"] == 0
    assert runs == []

    refreshed = X.refresh_wire_lot(api, light_heat["id"])
    assert refreshed["reserved_kg"] == 0.0
    assert refreshed["on_hand_kg"] == 1.0
    assert refreshed["received_kg"] == 1.0
    A.assert_decimal_places(refreshed["reserved_kg"], 3, "reserved_kg")
    A.assert_decimal_places(refreshed["on_hand_kg"], 3, "on_hand_kg")
    A.assert_wire_ledger_conserved(refreshed)

    setup = X.refresh_setup(api, world.setup_id)
    assert setup["setup_status"] == C.SETUP_ACTIVE


def test_every_lot_creation_gate_is_satisfied_on_the_canonical_chain(
    api: ApiClient,
) -> None:
    """The positive counterpart to every refusal above.

    A complete, heat-treated, peened, capable run on a quoted and fully approved
    program allocates its first thousand pieces, and the lot snapshots the
    commercial terms the quote left on the program while the ledger conserves.

    PRD §3.11: "The run's `process_status` must be `COMPLETE`, otherwise `ERR_RUN_NOT_COMPLETE` (HTTP 409); its `quality_status` must be `OPEN` or `DISPOSITIONED_ACCEPT`, and a held or scrapped run answers `ERR_RUN_ON_SPC_HOLD` (HTTP 409)."
    PRD §3.11: "The PPAP standing gate requires both that the design's `release_status` is `PROTOTYPE_RELEASED` or `PRODUCTION_RELEASED` **and** that the newest qualification submission by `created_at` for the program and the run's design has a `submission_status` of `APPROVED` or `INTERIM_APPROVED`; a failure answers `ERR_PPAP_NOT_APPROVED` (HTTP 422)."
    PRD §3.11: "Heat treatment must be finished and peening honoured: the run's `heat_treat_state` must be `COMPLETE`, and either the design does not require shot peening or the run's `peening_verified` is true, otherwise `ERR_HEAT_TREAT_INCOMPLETE` (HTTP 422)."
    PRD §3.11: "The run's `min_ppk_observed` must be non-null and at least the program's `required_ppk`, otherwise `ERR_PPK_BELOW_PROGRAM_FLOOR` (HTTP 422) — a run that has never taken a safety-critical SPC subgroup has a null `min_ppk_observed` and fails here."
    PRD §3.11: "A lot that survives all of that opens in `lot_status` `ALLOCATED` with `packaging_method` null, and it snapshots the commercial terms at creation: `unit_price_cents` from the program's `quoted_unit_price_cents`, `tooling_amort_per_piece_cents` from the program's `quoted_tooling_amort_per_piece_cents`, and `extended_price_cents` as `piece_count` multiplied by `unit_price_cents`."
    PRD §3.11: "`tooling_recovery_cents` starts at 0 and `shipped_at` and `quarantine_reason` start null."
    PRD §3.11: "On the program, `open_commitment_pieces` decreases by `piece_count` and `allocated_pieces` increases by it, conserving `committed_pieces`, and `delivery_posture` is re-derived."
    PRD §3.11: "9. `quoted_tooling_amort_per_piece_cents` is the smaller of the raw ask and the cap."
    PRD §3.11: "10. `quoted_unit_price_cents` is the discounted unit cost plus that per-piece amortization, rounded to whole cents."
    PRD §3.10: "Hop four sets the program's `quote_frozen` to true — the commercial terms are now contractual and no further quote may be run — and re-derives `delivery_posture`, which reaches `ON_TRACK` on a program with no quarantined lots and no held run."

    Design: Corner/validations/every_lot_creation_gate_is_satisfied_on_the_canonical_chain
    """
    world = X.build_world(api, "approved")
    assert world.design["release_status"] == C.RELEASE_PRODUCTION
    assert world.submission["submission_status"] == C.SUBMISSION_APPROVED

    run = X.refresh_run(api, world.run_id)
    assert run["process_status"] == C.PROCESS_COMPLETE
    assert run["quality_status"] == C.QUALITY_OPEN
    assert run["heat_treat_state"] == C.HEAT_TREAT_COMPLETE
    assert run["peening_verified"] is True
    assert run["produced_pieces"] == 25_500
    assert run["min_ppk_observed"] >= world.program["required_ppk"]

    quote = A.expected_quote(0.021185, 850, 1.8, 26_000, 4_800_000)
    program = X.refresh_program(api, world.program_id)
    assert program["quoted_unit_price_cents"] == quote["quoted_unit_price_cents"] == 24
    assert (
        program["quoted_tooling_amort_per_piece_cents"]
        == quote["quoted_tooling_amort_per_piece_cents"]
        == 4
    )
    assert program["minimum_order_quantity"] == 1_000

    data = validate_success(
        api.create_lot(
            F.lot_payload(world.run_id, world.program_id, 1_000),
            PROGRAM_MANAGER_HEADERS,
        ),
        201,
    )
    assert data["lot_status"] == C.LOT_ALLOCATED
    assert data["piece_count"] == 1_000
    assert data["unit_price_cents"] == 24
    assert data["tooling_amort_per_piece_cents"] == 4
    assert data["extended_price_cents"] == 1_000 * 24 == 24_000
    assert data["tooling_recovery_cents"] == 0
    assert data["packaging_method"] is None
    assert data["shipped_at"] is None
    assert data["quarantine_reason"] is None
    for field in (
        "unit_price_cents",
        "tooling_amort_per_piece_cents",
        "extended_price_cents",
        "tooling_recovery_cents",
    ):
        assert isinstance(data[field], int), field

    program = X.refresh_program(api, world.program_id)
    assert program["allocated_pieces"] == 1_000
    assert program["open_commitment_pieces"] == 499_000
    assert program["committed_pieces"] == 500_000
    posture = A.expected_delivery_posture(True, 0, False)
    assert posture == C.POSTURE_ON_TRACK
    assert program["delivery_posture"] == posture
    A.assert_commitment_conserved(program)
