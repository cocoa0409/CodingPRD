"""Submission side effects: shot-clock length, provisional fee rounding,
the incompleteness/cure tolling cycle, and submit preconditions.

Difficulty: combinatorial_formula, non_linear_state_machine.
Corner: calculations, endpoints, state_machines.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    COLLOCATION_NODE_FEE_CENTS,
    register_applicant, create_structure, create_segment, set_clock,
    open_application, add_node, submit, record_completeness, cure,
    fetch_invoice, make_applicant_headers, TEST_USERS,
)


def _build_two_col_one_newpole_submitted():
    """2 COLLOCATION + 1 NEW_POLE batch submitted at clock 2026-06-01."""
    applicant = register_applicant()
    ss_col = create_structure(max_collocations=2)
    ss_np = create_structure(max_collocations=1, structure_type="NEW_POLE")
    seg = create_segment()
    set_clock("2026-06-01T00:00:00Z")
    app = open_application(applicant["id"], project_name="P3")
    add_node(app["id"], applicant["id"], ss_col["id"], seg["id"], facility_type="COLLOCATION")
    add_node(app["id"], applicant["id"], ss_col["id"], seg["id"], facility_type="COLLOCATION")
    add_node(app["id"], applicant["id"], ss_np["id"], seg["id"],
             facility_type="NEW_POLE", proposed_construction_date="2029-06-15T00:00:00Z")
    submitted = submit(app["id"], applicant["id"])
    return applicant, submitted


# ─── Difficulty: shot_clock_base_days_conditional_max ─────────────────────
def test_new_pole_batch_forces_90_day_base(api):
    """PRD §3.2: "The `shot_clock_base_days` is 60 days when every node in the batch
    is a collocation, and 90 days when any node is a new pole — a single new pole
    forces the longer federal clock."

    Design: Difficulty/combinatorial_formula/shot_clock_base_days_conditional_max
    """
    _, submitted = _build_two_col_one_newpole_submitted()
    assert submitted["shot_clock_base_days"] == 90


def test_new_pole_batch_deadline_is_submit_plus_90_days(api):
    """PRD §3.2: "The `shot_clock_deadline` is `submitted_at` plus that base number
    of days plus any accumulated tolling days (initially zero)."

    Design: Difficulty/combinatorial_formula/shot_clock_base_days_conditional_max
    """
    _, submitted = _build_two_col_one_newpole_submitted()
    assert submitted["shot_clock_deadline"] == "2026-08-30T00:00:00.000Z"


# ─── Difficulty: application_fee_round_per_node_then_sum ───────────────────
def _submit_three_collocation_batch():
    applicant = register_applicant()
    ss = create_structure(max_collocations=3)
    seg = create_segment()
    set_clock("2026-06-01T00:00:00Z")
    app = open_application(applicant["id"], project_name="P4")
    for _ in range(3):
        add_node(app["id"], applicant["id"], ss["id"], seg["id"], facility_type="COLLOCATION")
    submit(app["id"], applicant["id"])
    return applicant, app


def test_provisional_fee_sums_per_node_rounded_amounts(api):
    """PRD §3.7: "Each node's base fee is 95,066 cents for a new pole and 47,533
    cents for a collocation. To that base a ROW administrative technology surcharge
    of 8.25 percent is applied, and the surcharged per-node fee is rounded half-up
    to whole cents."

    Design: Difficulty/combinatorial_formula/application_fee_round_per_node_then_sum
    """
    applicant, app = _submit_three_collocation_batch()
    invoice = fetch_invoice(app["id"], applicant["id"])
    assert invoice["fee_variant"] == "PROVISIONAL"
    assert invoice["assessed_amount_cents"] == 154362


def test_provisional_fee_rounds_per_node_not_the_sum(api):
    """PRD §2.8: "each node's surcharged fee is rounded to whole cents first, and
    only then are the per-node amounts summed. Rounding the sum instead of the
    parts would differ by a cent on some batches and is not permitted."

    Design: Difficulty/combinatorial_formula/application_fee_round_per_node_then_sum
    """
    applicant, app = _submit_three_collocation_batch()
    invoice = fetch_invoice(app["id"], applicant["id"])
    # Per-node rounding: 3 * 51454 == 154362 (sum-then-round would be 154363).
    assert invoice["assessed_amount_cents"] == 3 * COLLOCATION_NODE_FEE_CENTS
    assert invoice["assessed_amount_cents"] != 154363


# ─── Difficulty: application_incomplete_cure_cycle ────────────────────────
def _submit_then_incomplete_then_cure():
    applicant = register_applicant()
    ss = create_structure(max_collocations=2)
    seg = create_segment()
    set_clock("2026-06-01T00:00:00Z")
    app = open_application(applicant["id"], project_name="P5")
    add_node(app["id"], applicant["id"], ss["id"], seg["id"], facility_type="COLLOCATION")
    submit(app["id"], applicant["id"])
    set_clock("2026-06-10T00:00:00Z")
    record_completeness(app["id"], complete=False, deficiencies="structural load calc missing")
    set_clock("2026-06-20T00:00:00Z")
    return applicant, cure(app["id"], applicant["id"])


def test_cure_returns_to_submitted_and_accumulates_toll(api):
    """PRD §3.3: "On cure, that latest notice's `cured_at` is set to the current
    clock and its `toll_days` is set to the elapsed time from `issued_at` to
    `cured_at`, expressed in days; that same quantity is added to the application's
    `toll_days_accumulated`;"

    Design: Difficulty/non_linear_state_machine/application_incomplete_cure_cycle
    """
    _, cured = _submit_then_incomplete_then_cure()
    assert cured["status"] == "SUBMITTED"
    assert cured["toll_days_accumulated"] == 10


def test_cure_extends_deadline_by_toll_days(api):
    """PRD §3.3: "the `shot_clock_deadline` is recomputed as `submitted_at` plus
    `shot_clock_base_days` days plus the running `toll_days_accumulated`."

    Design: Difficulty/non_linear_state_machine/application_incomplete_cure_cycle
    """
    _, cured = _submit_then_incomplete_then_cure()
    # base 60 from 2026-06-01 => 2026-07-31; +10 toll => 2026-08-10.
    assert cured["shot_clock_deadline"] == "2026-08-10T00:00:00.000Z"


# ─── Corner: collocation_only_shot_clock_is_60_days ───────────────────────
def test_collocation_only_batch_uses_60_day_clock(api):
    """PRD §3.2: "The `shot_clock_base_days` is 60 days when every node in the batch
    is a collocation, and 90 days when any node is a new pole — a single new pole
    forces the longer federal clock."

    Design: Corner/calculations/collocation_only_shot_clock_is_60_days
    """
    applicant = register_applicant()
    ss = create_structure(max_collocations=2)
    seg = create_segment()
    set_clock("2026-06-01T00:00:00Z")
    app = open_application(applicant["id"])
    add_node(app["id"], applicant["id"], ss["id"], seg["id"], facility_type="COLLOCATION")
    submitted = submit(app["id"], applicant["id"])
    assert submitted["shot_clock_base_days"] == 60
    assert submitted["shot_clock_deadline"] == "2026-07-31T00:00:00.000Z"


# ─── Corner: fee_invoice_reverse_reachable_from_application ────────────────
def test_fee_invoice_reachable_as_length_one_list(api):
    """PRD §3.7: "Every submitted application carries exactly one fee invoice,
    retrievable as a zero-or-one list. At submission the invoice is raised with
    `fee_variant` of `PROVISIONAL`, `status` of `OPEN`, and `assessed_amount_cents`
    computed over all filed nodes;"

    Design: Corner/endpoints/fee_invoice_reverse_reachable_from_application
    """
    applicant = register_applicant()
    ss = create_structure(max_collocations=2)
    seg = create_segment()
    set_clock("2026-06-01T00:00:00Z")
    app = open_application(applicant["id"])
    add_node(app["id"], applicant["id"], ss["id"], seg["id"], facility_type="COLLOCATION")
    submit(app["id"], applicant["id"])
    data, _ = validate_paginated(
        api.get_application_fee_invoice(app["id"], make_applicant_headers(applicant["id"]))
    )
    assert len(data) == 1
    assert data[0]["fee_variant"] == "PROVISIONAL"
    assert data[0]["assessed_amount_cents"] == 51454
    assert data[0]["outstanding_amount_cents"] == 51454


# ─── Corner: submit_without_master_agreement_rejected ─────────────────────
def test_submit_without_master_agreement_rejected(api):
    """PRD §3.2: "The submission is refused unless the acting applicant owns the
    application, the provider's `master_agreement_signed` is true (otherwise
    `ERR_MASTER_AGREEMENT_REQUIRED`), and the batch contains at least one node with
    every node fully specified"

    Design: Corner/state_machines/submit_without_master_agreement_rejected
    """
    applicant = register_applicant(sign=False)
    ss = create_structure(max_collocations=2)
    seg = create_segment()
    app = open_application(applicant["id"])
    add_node(app["id"], applicant["id"], ss["id"], seg["id"], facility_type="COLLOCATION")
    res = api.submit_application(app["id"], make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_MASTER_AGREEMENT_REQUIRED", 422)


# ─── Corner: submit_with_no_nodes_rejected ────────────────────────────────
def test_submit_with_no_nodes_rejected(api):
    """PRD §3.2: "the batch contains at least one node with every node fully
    specified — each carrying its support structure, its segment, and its
    construction date (otherwise `ERR_NO_NODES`)."

    Design: Corner/state_machines/submit_with_no_nodes_rejected
    """
    applicant = register_applicant()
    app = open_application(applicant["id"])
    res = api.submit_application(app["id"], make_applicant_headers(applicant["id"]))
    validate_error(res, "ERR_NO_NODES", 422)


# ─── Corner: add_node_to_non_draft_application_rejected ───────────────────
def test_add_node_to_submitted_application_rejected(api):
    """PRD §3.2: "Adding a node to an application that is not in `DRAFT` is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/add_node_to_non_draft_application_rejected
    """
    applicant = register_applicant()
    ss = create_structure(max_collocations=2)
    seg = create_segment()
    app = open_application(applicant["id"])
    add_node(app["id"], applicant["id"], ss["id"], seg["id"], facility_type="COLLOCATION")
    submit(app["id"], applicant["id"])
    res = api.add_node(
        app["id"],
        {
            "facility_type": "COLLOCATION",
            "support_structure_id": ss["id"],
            "row_segment_id": seg["id"],
            "proposed_construction_date": "2026-06-15T00:00:00Z",
        },
        make_applicant_headers(applicant["id"]),
    )
    validate_error(res, "ERR_INVALID_STATE", 409)
