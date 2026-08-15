"""Uniform room and the batch-driven cleaning cycle: issuance gates, per-line
pricing with pinned rounding order, and per-student cleaning debits."""
from test_helpers import (
    EQUIPMENT_HEADERS,
    READER_HEADERS,
    ApiErrorId,
    attach_to_batch,
    create_cleaning_batch,
    create_enrolled_student,
    create_open_program,
    create_uniform,
    create_uniform_assignment_payload,
    get_student,
    issue_uniform,
    receive_batch,
    send_batch,
    validate_error,
    validate_success,
)

READER = READER_HEADERS
EQUIPMENT_H = EQUIPMENT_HEADERS


def test_send_empty_batch_rejected(api, equipment_headers):
    """PRD §3.4: "Sending the batch requires it `OPEN` (else `ERR_BATCH_NOT_OPEN`) with at least one garment attached (else `ERR_BATCH_EMPTY`); sending moves every attached garment to `AT_CLEANER`, moves the batch to `SENT`, and increments its `version`."

    Design: Corner/state_machines/batch_send_requires_nonempty_batch
    """
    program = create_open_program(season_name="BE")
    batch = create_cleaning_batch(program["id"])
    assert batch["status"] == "OPEN"
    assert batch["garment_count"] == 0

    resp = api.send_cleaning_batch(batch["id"], equipment_headers)
    validate_error(resp, ApiErrorId.ERR_BATCH_EMPTY)
    batch = validate_success(api.get_cleaning_batch(batch["id"], READER))
    assert batch["status"] == "OPEN"


def test_plume_requires_currently_issued_shako(api, equipment_headers):
    """PRD §3.4: "The plumage rule is cross-garment: issuing a `PLUME` requires the same student to currently hold an `ISSUED` `SHAKO`, else `ERR_MATCHING_GARMENT_REQUIRED`."

    Design: Corner/validations/plume_requires_issued_shako
    """
    program = create_open_program(season_name="MG")
    student = create_enrolled_student(program["id"], full_name="MG")
    plume = create_uniform(program["id"], garment_type="PLUME", size_label="STD")
    shako = create_uniform(program["id"], garment_type="SHAKO", size_label="7")

    blocked = api.create_uniform_assignment(
        create_uniform_assignment_payload(student["id"], plume["id"]),
        equipment_headers)
    validate_error(blocked, ApiErrorId.ERR_MATCHING_GARMENT_REQUIRED)

    issue_uniform(student["id"], shako["id"])
    allowed = validate_success(api.create_uniform_assignment(
        create_uniform_assignment_payload(student["id"], plume["id"]),
        equipment_headers), 201)
    assert allowed["status"] == "ISSUED"
    assert allowed["uniform_id"] == plume["id"]


def test_second_issued_garment_of_same_type_rejected(api, equipment_headers,
                                                     reader_headers):
    """PRD §3.4: "A student may hold at most one `ISSUED` garment of each `garment_type` — a second issue of the same type is rejected with `ERR_GARMENT_TYPE_ALREADY_ISSUED`."

    Design: Corner/validations/garment_type_uniqueness_per_student
    """
    program = create_open_program(season_name="GU")
    student = create_enrolled_student(program["id"], full_name="GU")
    jacket1 = create_uniform(program["id"], garment_type="JACKET", size_label="M")
    jacket2 = create_uniform(program["id"], garment_type="JACKET", size_label="L")
    issue_uniform(student["id"], jacket1["id"])

    dup = api.create_uniform_assignment(
        create_uniform_assignment_payload(student["id"], jacket2["id"]),
        equipment_headers)
    validate_error(dup, ApiErrorId.ERR_GARMENT_TYPE_ALREADY_ISSUED)
    jacket2 = validate_success(api.get_uniform(jacket2["id"], reader_headers))
    assert jacket2["status"] == "IN_STORAGE", "rejected issuance leaves storage"


def _issue_then_return(api, program_id, student_id, garment_types):
    """Create one garment per type, issue them in order (SHAKO precedes PLUME so
    the plumage rule's currently-ISSUED requirement holds), then return all as
    NORMAL. Returns (uniforms, assignments)."""
    uniforms = [create_uniform(program_id, garment_type=g, size_label="7")
                for g in garment_types]
    assignments = [issue_uniform(student_id, u["id"]) for u in uniforms]
    for a in assignments:
        api_return = api.return_uniform_assignment(a["id"], {"soiling_level": "NORMAL"},
                                                   EQUIPMENT_H)
        assert 200 <= api_return.status_code < 300, api_return.text
    return uniforms, assignments


def test_eleven_garment_batch_prices_per_line_then_sums(api, reader_headers):
    """PRD §3.4: "The pinned rounding order is per-line first, then sum: each garment's line cost is its base price multiplied by one minus the discount fraction, rounded half up to integer cents, plus a 200-cent heavy-soiling surcharge when the returned garment's recorded `soiling_level` is `HEAVY`; the batch's `total_cost_cents` is the sum of those line costs." PRD §3.4: "the volume discount tier is chosen from `garment_count`: 0 percent for 1 to 10 garments, 15 percent for 11 to 30, and 25 percent for 31 or more."

    Design: Difficulty/combinatorial_formula/cleaning_batch_per_line_rounding_order
    """
    program = create_open_program(season_name="CL")
    student1 = create_enrolled_student(program["id"], full_name="U1", grade=9,
                                       section="WOODWIND")
    student2 = create_enrolled_student(program["id"], full_name="U2", grade=10,
                                       section="WOODWIND")
    student3 = create_enrolled_student(program["id"], full_name="U3", grade=11,
                                       section="WOODWIND")

    # Five types for S1, five for S2 (SHAKO issued before PLUME per the plumage
    # rule), one SHAKO for S3 — eleven garments, all returned NORMAL.
    uniforms, assignments = [], []
    for student in (student1, student2):
        u, a = _issue_then_return(api, program["id"], student["id"],
                                  ["JACKET", "BIBBERS", "SHAKO", "PLUME",
                                   "GLOVES"])
        uniforms.extend(u)
        assignments.extend(a)
    u, a = _issue_then_return(api, program["id"], student3["id"], ["SHAKO"])
    uniforms.extend(u)
    assignments.extend(a)

    batch = create_cleaning_batch(program["id"])
    for uniform in uniforms:
        attach_to_batch(batch["id"], uniform["id"])
    send_batch(batch["id"])
    received = receive_batch(batch["id"])

    # 15% tier: 765 + 595 + 383 + 255 + 128 per full set, plus 383 for S3.
    assert received["status"] == "RECONCILED"
    assert received["garment_count"] == 11
    assert float(received["discount_pct"]) == 0.15
    assert received["total_cost_cents"] == 4635, (
        "per-line round_half_up then sum: 2 * 2126 + 383")

    assert get_student(student1["id"])["account_balance_cents"] == 2126
    assert get_student(student2["id"])["account_balance_cents"] == 2126
    assert get_student(student3["id"])["account_balance_cents"] == 383

    garment = validate_success(api.get_uniform(uniforms[0]["id"], reader_headers))
    assert garment["status"] == "IN_STORAGE"
    assert garment["cleaning_count"] == 1
    assert garment["cleaning_batch_id"] is None

    first_assignment = validate_success(
        api.get_uniform_assignment(assignments[0]["id"], reader_headers))
    assert first_assignment["cleaning_fee_cents"] == 765, (
        "JACKET line at the 15 percent tier: round_half_up(900 * 0.85)")


def test_per_line_order_matches_documented_shako_plume_example(
        api, reader_headers):
    """PRD §3.4: "The alternative order — summing base prices, applying the discount once, and rounding a single total — is forbidden, because the two orders genuinely disagree: six shakos and six plumes at the 15 percent tier price at 3828 cents under per-line rounding (six lines of 383 plus six lines of 255) against 3825 under sum-then-round."

    Design: Difficulty/combinatorial_formula/cleaning_batch_per_line_rounding_order
    """
    program = create_open_program(season_name="CL2")
    uniforms = []
    for i in range(6):
        student = create_enrolled_student(program["id"], full_name=f"SP{i}",
                                          grade=10, section="BRASS")
        u, _a = _issue_then_return(api, program["id"], student["id"],
                                   ["SHAKO", "PLUME"])
        uniforms.extend(u)

    batch = create_cleaning_batch(program["id"])
    for u in uniforms:
        attach_to_batch(batch["id"], u["id"])
    send_batch(batch["id"])
    received = receive_batch(batch["id"])

    assert received["garment_count"] == 12
    assert float(received["discount_pct"]) == 0.15
    assert received["total_cost_cents"] == 3828, (
        "six lines of 383 plus six lines of 255; sum-then-round would give 3825")
