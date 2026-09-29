"""The lot's two independent dimensions and the cross-entity release gates."""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    citrus_approved_formula,
    compound_lot,
    create_revision,
    read_formula,
    read_lot,
    record_qc,
    release_lot,
)
from test_helpers.test_users import LAB_COMPOUNDER, LAB_COMPOUNDER_ID, LAB_QC_ID


def test_a_passing_qc_verdict_does_not_release_the_lot(api):
    """QC and disposition are two dimensions; PASSED leaves the lot HELD.

    The PRD keeps the two dimensions apart: "a new lot starts with `qc_status`
    at `PENDING`, `disposition_status` at `HELD`", and a passing verdict
    "moves `PENDING → PASSED` and deliberately leaves the disposition
    dimension exactly where it was; passing QC does not release anything".

    Design: Difficulty/non_linear_state_machine/sample_lot_qc_and_disposition_dimensions_advance_independently
    """
    scenario = citrus_approved_formula(api)
    lot = compound_lot(api, scenario["formula"]["id"], batch_size_g=500)

    assert lot["qc_status"] == "PENDING"
    assert lot["disposition_status"] == "HELD"

    after_qc = record_qc(api, lot["id"], "PASSED")

    assert after_qc["qc_status"] == "PASSED"
    assert after_qc["disposition_status"] == "HELD"

    released = release_lot(api, lot["id"])
    assert released["qc_status"] == "PASSED"
    assert released["disposition_status"] == "RELEASED"


def test_a_failing_qc_verdict_scraps_the_lot_without_any_release_call(api):
    """FAILED crosses the dimensions and drives HELD to SCRAPPED by itself.

    The PRD says "a `result` of `FAILED` moves `PENDING → FAILED` and does
    reach across dimensions: the lot's `disposition_status` moves `HELD →
    SCRAPPED`", so no release call is involved.

    Design: Difficulty/non_linear_state_machine/sample_lot_qc_and_disposition_dimensions_advance_independently
    """
    scenario = citrus_approved_formula(api)
    lot = compound_lot(api, scenario["formula"]["id"], batch_size_g=200)

    failed = record_qc(api, lot["id"], "FAILED", qc_note="Off-note detected in the top")

    assert failed["qc_status"] == "FAILED"
    assert failed["disposition_status"] == "SCRAPPED"


def test_lot_numbers_are_minted_per_brief_iteration_in_creation_order(api):
    """Two lots of one formula take the L001 and L002 suffixes.

    The PRD says `lot_number` "concatenates the brief's `brief_code`, then a
    literal `-I` followed by the formula's iteration number zero-padded to two
    digits, then a literal `-L` followed by that sequence position zero-padded
    to three digits", the position being "one more than the number of lots
    already recorded against the same formula with an earlier creation
    timestamp".

    Design: Difficulty/non_linear_state_machine/sample_lot_qc_and_disposition_dimensions_advance_independently
    """
    scenario = citrus_approved_formula(api)
    lot_a = compound_lot(api, scenario["formula"]["id"], batch_size_g=500)
    lot_b = compound_lot(api, scenario["formula"]["id"], batch_size_g=200)

    assert lot_a["lot_number"] == "BRF-0001-I01-L001"
    assert lot_b["lot_number"] == "BRF-0001-I01-L002"


def test_the_compounder_and_the_qc_operator_are_recorded_separately(api):
    """Two different users are stamped on the two dimensions.

    The PRD says compounding "records the compounding operator's `X-User-ID`
    into `compounded_by_user_id`" and that "either verdict records the recorder
    into `qc_by_user_id`", the recorder being required "to differ from
    `compounded_by_user_id`".

    Design: Difficulty/non_linear_state_machine/sample_lot_qc_and_disposition_dimensions_advance_independently
    """
    scenario = citrus_approved_formula(api)
    lot = compound_lot(api, scenario["formula"]["id"], batch_size_g=500)
    record_qc(api, lot["id"], "PASSED", qc_note="Profile matches the bench reference")
    released = release_lot(api, lot["id"])

    assert released["compounded_by_user_id"] == LAB_COMPOUNDER_ID
    assert released["qc_by_user_id"] == LAB_QC_ID
    assert released["available_g"] == 500
    assert released["allocated_g"] == 0


def test_release_is_refused_once_a_revision_supersedes_the_formula(api):
    """The lot's own state is fine; the superseded formula blocks the release.

    The PRD requires for release that "its formula must still be
    `APPROVED`, else `ERR_FORMULA_NOT_APPROVED`", and §2.11 puts that
    cross-entity guard ahead of the lot's own-state guard.  A revision drives
    the predecessor "`APPROVED → SUPERSEDED`".

    Design: Difficulty/cross_entity_state_dependency/lot_release_requires_its_formula_to_still_be_approved
    """
    scenario = citrus_approved_formula(api)
    formula = scenario["formula"]
    lot = compound_lot(api, formula["id"], batch_size_g=500)
    passed = record_qc(api, lot["id"], "PASSED")
    assert passed["qc_status"] == "PASSED"
    assert passed["disposition_status"] == "HELD"

    observed = read_formula(api, formula["id"])
    create_revision(api, formula["id"], observed["version"],
                    name="Citrus Top Note F1 r2", carry_components=True)

    response = api.release_sample_lot(lot["id"], LAB_COMPOUNDER)
    validate_error(response, ApiErrorId.ERR_FORMULA_NOT_APPROVED.value)

    held = read_lot(api, lot["id"])
    assert held["disposition_status"] == "HELD"
    assert held["available_g"] == 500


def test_the_revision_records_the_supersession_on_both_formulas(api):
    """The predecessor points forward, the successor points back at iteration 2.

    The PRD says the predecessor "goes `APPROVED → SUPERSEDED` ... has
    `superseded_by_formula_id` set to the new formula", while "a successor
    formula is created in `DRAFT` with `parent_formula_id` pointing back at the
    predecessor and `iteration_no` derived as one more than the number of
    formulas already recorded against the same brief".

    Design: Difficulty/cross_entity_state_dependency/lot_release_requires_its_formula_to_still_be_approved
    """
    scenario = citrus_approved_formula(api)
    formula = scenario["formula"]
    observed = read_formula(api, formula["id"])

    revision = create_revision(api, formula["id"], observed["version"],
                               name="Citrus Top Note F1 r2", carry_components=True)

    predecessor = read_formula(api, formula["id"])
    assert predecessor["status"] == "SUPERSEDED"
    assert predecessor["superseded_by_formula_id"] == revision["id"]

    successor = read_formula(api, revision["id"])
    assert successor["status"] == "DRAFT"
    assert successor["parent_formula_id"] == formula["id"]
    assert successor["iteration_no"] == 2
