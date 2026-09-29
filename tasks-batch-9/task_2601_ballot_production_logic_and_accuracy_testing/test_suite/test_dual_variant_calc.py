"""Derivations that answer two different figures for the same stored data.

Three families of the ballot-production service compute one quantity under two
declared variants, and the variants are not relabellings of one another:

* the printed layout of a ballot style, read on the as-filed roster versus the
  certified roster, where the roster size is itself the rotation modulus;
* a print job's invoice, billed once as an estimate for the whole order and then
  rebilled lot by lot on delivery with the quality credit applied;
* the ballot-accountability worksheet, scoped to the paper still in the field
  versus the paper physically returned.

Every expected figure below is the one the contract fixes for these inputs:
invoice cents, defect basis points, worksheet lines and printed positions.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as asserts
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_client import BallotProductionApiClient
from test_helpers.constants import (
    ACCOUNTABILITY_BALANCED,
    ACCOUNTABILITY_OUT_OF_BALANCE,
    ACCOUNTABILITY_PENDING,
    BASIS_CERTIFIED,
    BASIS_FINAL_CANVASS,
    BASIS_PRELIMINARY,
    BASIS_PROVISIONAL,
    CANDIDATE_DISQUALIFIED,
    CLOCK_START,
    DISTRICT_D07,
    DISTRICT_D12,
    DISTRICT_D19,
    DISTRICT_D99,
    INVOICE_ESTIMATE,
    INVOICE_FINAL,
    JOB_DELIVERED,
    JOB_QC_PASSED,
    LOT_CODE_1,
    LOT_CODE_2,
    LOT_CODE_3,
    LOT_IN_TRANSIT,
    LOT_ISSUED,
    LOT_RETURNED,
    ORDER_ALPHABETICAL,
    PHASE_DEPLOYED,
    ROTATION_DISTRICT,
    SEAL_1,
    SEAL_2,
    SEAL_3,
    SESSION_START,
    STYLE_CODE_LOW,
    STYLE_CODE_MAIN,
)


# ─── Private world builders ──────────────────────────────────────────────────

def _rotating_layout_world(client: BallotProductionApiClient):
    """A four-candidate district-rotated contest on a style that carries seed 1.

    The style ``S-050`` over district ``D-99`` is created first so that ``S-100``
    ranks second by style code and therefore holds rotation seed 1, and ``D-12``
    is the second of the three districts ``S-100`` prints, so the district offset
    is 1 as well. After the ballot order is frozen, Dawson is disqualified.
    """
    sc = fx.new_election(client, CLOCK_START, rotation_policy=ROTATION_DISTRICT,
                         candidate_order_method=ORDER_ALPHABETICAL)
    contest_id = fx.add_contest(sc, rotation_required=True)
    alvarez = fx.add_candidate(sc, full_name="Ana Alvarez", ballot_name="Alvarez",
                               filing_received_at="2026-06-01T09:00:00Z")
    brooks = fx.add_candidate(sc, full_name="Ben Brooks", ballot_name="Brooks",
                              filing_received_at="2026-06-02T09:00:00Z")
    chen = fx.add_candidate(sc, full_name="Cai Chen", ballot_name="Chen",
                            filing_received_at="2026-06-03T09:00:00Z")
    dawson = fx.add_candidate(sc, full_name="Dee Dawson", ballot_name="Dawson",
                              filing_received_at="2026-06-04T09:00:00Z")
    fx.certify_contest(sc)
    fx.add_style(sc, style_code=STYLE_CODE_LOW, district_codes=[DISTRICT_D99])
    style_id = fx.add_style(sc, style_code=STYLE_CODE_MAIN,
                            district_codes=[DISTRICT_D07, DISTRICT_D12, DISTRICT_D19])
    get_success_data(sc.client.certify_ballot_order(sc.election_id, users.DIRECTOR))
    get_success_data(
        sc.client.disqualify_candidate(
            dawson, f.disqualify_payload("Withdrew after filing deadline"), users.DIRECTOR))
    return sc, contest_id, style_id, (alvarez, brooks, chen, dawson)


def _layout(sc, style_id: str, basis: str):
    """Read one style layout under an explicitly requested basis."""
    return validate_success(
        sc.client.get_layout(style_id, users.COORDINATOR, f.layout_params(basis)), 200)


def _contest_block(layout, contest_id: str):
    """Return the single contest block a layout printed for ``contest_id``."""
    blocks = layout.get("contests")
    assert isinstance(blocks, list), f"layout.contests must be a list, got {blocks!r}"
    matches = [block for block in blocks if block.get("contest_id") == contest_id]
    assert len(matches) == 1, (
        f"layout must carry exactly one block for contest {contest_id}, found {len(matches)}")
    return matches[0]


def _base_indices(block):
    """Map candidate id to the base_order_index the layout reported for it."""
    return {row.get("candidate_id"): row.get("base_order_index")
            for row in block.get("candidates", [])}


def _locked_job_world(client: BallotProductionApiClient):
    """A locked election with one 12500-ballot order at 8450 cents per thousand."""
    sc = fx.styles_locked(client, CLOCK_START, registered_voter_count=100)
    fx.add_vendor(sc)
    fx.add_print_job(sc, quantity_ordered=12500)
    return sc


def _split_manifest():
    """The three-pallet manifest whose per-lot rounding loses a cent."""
    return [
        f.manifest_line(LOT_CODE_1, 4001, SEAL_1),
        f.manifest_line(LOT_CODE_2, 4001, SEAL_2),
        f.manifest_line(LOT_CODE_3, 4498, SEAL_3),
    ]


def _three_lot_deployed_world(client: BallotProductionApiClient):
    """A deployed election whose three lots carry 3000, 2000 and 1 issued ballots.

    The first two lots have reported their board counts; the third is still in
    the field with no counts at all.
    """
    sc = fx.styles_locked(client, CLOCK_START, registered_voter_count=100)
    fx.add_vendor(sc)
    fx.add_print_job(sc, quantity_ordered=12500)
    fx.printed_job(sc)
    fx.inspect_job(sc, sample_size=500, defect_count=6)
    fx.deliver_job(sc, lots=_split_manifest())
    lot_one, lot_two, lot_three = sc.lot_ids
    fx.receive_lot(sc, lot_one, SEAL_1, 4001)
    fx.issue_lot(sc, lot_one, issue_quantity=3000)
    fx.receive_lot(sc, lot_two, SEAL_2, 4001)
    fx.issue_lot(sc, lot_two, issue_quantity=2000)
    fx.receive_lot(sc, lot_three, SEAL_3, 4498)
    fx.issue_lot(sc, lot_three, issue_quantity=1)
    fx.add_tabulator(sc)
    fx.program_unit(sc)
    fx.add_test_deck(sc)
    fx.schedule_session(sc)
    fx.sign_in_observers(sc)
    fx.set_clock(client, SESSION_START)
    fx.start_session(sc)
    fx.record_matching_results(sc)
    fx.deploy_unit(sc)
    get_success_data(sc.client.deploy_election(sc.election_id, users.DIRECTOR))
    fx.return_lot_counts(sc, lot_one, 2900, 30, 20)
    fx.return_lot_counts(sc, lot_two, 1880, 25, 34)
    return sc, (lot_one, lot_two, lot_three)


def _worksheet(sc, basis: str):
    """Read the accountability worksheet under an explicit basis."""
    return validate_success(
        sc.client.get_accountability(sc.election_id, users.DIRECTOR,
                                     f.accountability_params(basis)), 200)


# ─── The printed layout on the as-filed roster versus the certified roster ────

def test_dv_layout_provisional_basis_prints_all_four_filers_over_a_modulus_of_four(client):
    """The as-filed layout keeps the disqualified filer, so the modulus is four.

    PRD Section 3.2: "On the `PROVISIONAL_BASIS` the candidate set is every candidate who ever filed — those in `FILED`, `CERTIFIED` and `DISQUALIFIED` alike."

    Design: Difficulty/dual_variant_calc/dv_candidate_layout_provisional_versus_certified_basis
    """
    sc, contest_id, style_id, (alvarez, brooks, chen, dawson) = _rotating_layout_world(client)

    layout = _layout(sc, style_id, BASIS_PROVISIONAL)

    asserts.assert_fields_equal(
        layout,
        {
            "style_id": style_id,
            "style_code": STYLE_CODE_MAIN,
            "basis": BASIS_PROVISIONAL,
            "rotation_policy": ROTATION_DISTRICT,
            "rotation_seed_index": 1,
            "contest_count": 1,
            "candidate_count": 4,
        },
        "provisional layout")
    asserts.assert_printed_positions(
        layout, contest_id,
        {alvarez: 3, brooks: 4, chen: 1, dawson: 2})
    block = _contest_block(layout, contest_id)
    assert _base_indices(block) == {alvarez: 0, brooks: 1, chen: 2, dawson: 3}, (
        "the as-filed roster ranks all four filers 0 through 3")
    assert [row["printed_position"] for row in block["candidates"]] == [1, 2, 3, 4], (
        "the layout emits its candidates in printed_position ascending order")


def test_dv_layout_certified_basis_drops_the_disqualified_filer_and_shrinks_the_modulus(client):
    """The certified layout prints only the three certified names, over a modulus of three.

    PRD Section 3.2: "On the `CERTIFIED_BASIS` the candidate set is only those in `CERTIFIED`."

    Design: Difficulty/dual_variant_calc/dv_candidate_layout_provisional_versus_certified_basis
    """
    sc, contest_id, style_id, (alvarez, brooks, chen, dawson) = _rotating_layout_world(client)

    layout = _layout(sc, style_id, BASIS_CERTIFIED)

    asserts.assert_fields_equal(
        layout,
        {
            "style_id": style_id,
            "style_code": STYLE_CODE_MAIN,
            "basis": BASIS_CERTIFIED,
            "rotation_policy": ROTATION_DISTRICT,
            "rotation_seed_index": 1,
            "contest_count": 1,
            "candidate_count": 3,
        },
        "certified layout")
    asserts.assert_printed_positions(
        layout, contest_id,
        {alvarez: 3, brooks: 1, chen: 2, dawson: None})
    block = _contest_block(layout, contest_id)
    assert _base_indices(block) == {alvarez: 0, brooks: 1, chen: 2}, (
        "the certified roster ranks the three survivors 0 through 2")
    assert [row["printed_position"] for row in block["candidates"]] == [1, 2, 3], (
        "the certified layout is a contiguous permutation of positions 1 to 3")


def test_dv_layout_bases_disagree_on_the_printed_position_of_the_same_candidate(client):
    """The same seed prints a surviving candidate in two different positions per basis.

    PRD Section 3.2: "Each candidate's `printed_position` is then the sum of its `base_order_index` and the offset, reduced modulo the rotation modulus, plus one — a one-based contiguous permutation of the positions from 1 to the roster size."

    Design: Difficulty/dual_variant_calc/dv_candidate_layout_provisional_versus_certified_basis
    """
    sc, contest_id, style_id, (alvarez, brooks, chen, dawson) = _rotating_layout_world(client)

    provisional = _layout(sc, style_id, BASIS_PROVISIONAL)
    certified = _layout(sc, style_id, BASIS_CERTIFIED)

    asserts.assert_printed_positions(provisional, contest_id, {brooks: 4, chen: 1})
    asserts.assert_printed_positions(certified, contest_id, {brooks: 1, chen: 2})
    assert provisional["candidate_count"] == 4
    assert certified["candidate_count"] == 3
    assert provisional["rotation_seed_index"] == certified["rotation_seed_index"] == 1, (
        "both reads run on the one stored seed, so only the roster size differs")


def test_dv_stored_base_order_index_follows_the_certified_basis_alone(client):
    """The stored certified indices recompact to 0, 1, 2 and the disqualified index is null.

    PRD Section 3.2: "In the first hop the candidate's `disqualified_reason` is stored, its `base_order_index` is cleared to null — a disqualified candidate holds no certified position — and the contest's `certified_candidate_count` is recomputed."

    Design: Difficulty/dual_variant_calc/dv_candidate_layout_provisional_versus_certified_basis
    """
    sc, contest_id, style_id, (alvarez, brooks, chen, dawson) = _rotating_layout_world(client)

    rows = sc.candidates_of(contest_id)

    assert asserts.find_by(rows, "id", alvarez)["base_order_index"] == 0
    assert asserts.find_by(rows, "id", brooks)["base_order_index"] == 1
    assert asserts.find_by(rows, "id", chen)["base_order_index"] == 2
    dawson_row = asserts.find_by(rows, "id", dawson)
    assert dawson_row["base_order_index"] is None, (
        "a disqualified candidate holds no certified position")
    assert dawson_row["status"] == CANDIDATE_DISQUALIFIED
    contest = sc.read_contest(contest_id)
    asserts.assert_fields_equal(
        contest, {"certified_candidate_count": 3, "ballot_order_index": 1}, "contest")


# ─── The estimate invoice versus the invoice rebilled at delivery ─────────────

def test_dv_estimate_invoice_rounds_the_whole_order_in_one_line(client):
    """Approving the press proof bills 12500 ballots as one rounded line of 105625 cents.

    PRD Section 3.6: "`invoice_subtotal_cents` is the ordered quantity multiplied by the contract rate and divided by 1000, rounded half up to a whole cent — one rounding for the whole order."

    Design: Difficulty/dual_variant_calc/dv_print_job_invoice_estimate_versus_final_rounding
    """
    sc = _locked_job_world(client)

    job = validate_success(sc.client.approve_press_proof(sc.job_id, users.DIRECTOR), 200)

    asserts.assert_fields_equal(
        job,
        {
            "invoice_basis": INVOICE_ESTIMATE,
            "invoice_subtotal_cents": 105625,
            "freight_cents": 45000,
            "defect_credit_cents": 0,
            "invoice_total_cents": 150625,
            "delivered_quantity": 0,
        },
        "print job")
    assert sc.read_election()["committed_print_cents"] == 150625, (
        "the election commits exactly the estimate total")


def test_dv_estimate_freight_sits_in_the_first_whole_tier(client):
    """A billing quantity of 12500 ballots carries the flat first-tier freight fee.

    PRD Section 3.6: "A billing quantity of 50 000 ballots or fewer carries 45 000 cents; a billing quantity above 50 000 but no more than 200 000 carries 90 000 cents; anything above 200 000 carries 150 000 cents."

    Design: Difficulty/dual_variant_calc/dv_print_job_invoice_estimate_versus_final_rounding
    """
    sc = _locked_job_world(client)

    job = validate_success(sc.client.approve_press_proof(sc.job_id, users.DIRECTOR), 200)

    assert job["freight_cents"] == 45000, "12500 ballots stay inside the first freight tier"
    assert job["invoice_total_cents"] == 150625, (
        "the estimate total is the 105625-cent subtotal plus the 45000-cent freight fee")


def test_dv_inspection_writes_the_cumulative_defect_rate_that_the_credit_will_use(client):
    """A 500-ballot sample with 6 defects derives 120 basis points and releases the job.

    PRD Section 3.6: "Sampling is **cumulative**, never per-call: `inspection_count` increases by one, the payload's sample size is added to the job's running `sample_size`, the payload's defect count is added to the running `defect_count`, and `defect_rate_bp` is re-derived as the running defect count multiplied by 10 000 and divided by the running sample size, rounded half up to whole basis points."

    Design: Difficulty/dual_variant_calc/dv_print_job_invoice_estimate_versus_final_rounding
    """
    sc = _locked_job_world(client)
    fx.printed_job(sc)

    job = validate_success(
        sc.client.inspect_print_job(sc.job_id, f.inspect_payload(500, 6), users.CUSTODIAN), 200)

    asserts.assert_fields_equal(
        job,
        {
            "sample_size": 500,
            "defect_count": 6,
            "defect_rate_bp": 120,
            "inspection_count": 1,
            "status": JOB_QC_PASSED,
        },
        "print job")


def test_dv_final_invoice_rounds_each_shipped_lot_and_then_sums_them(client):
    """Delivery rebills the job at 105624 cents, one cent under the estimate line.

    PRD Section 3.6: "`invoice_subtotal_cents` is computed lot by lot rather than in one line: the job's lots whose custody state is not `VOIDED` are taken in `lot_code` ascending order, each lot's shipped quantity is multiplied by the contract rate and divided by 1000 and **rounded half up to a whole cent individually**, and those per-lot amounts are then added together — round-then-sum, rather than the estimate's sum-then-round."

    Design: Difficulty/dual_variant_calc/dv_print_job_invoice_estimate_versus_final_rounding
    """
    sc = _locked_job_world(client)
    estimate = fx.printed_job(sc)
    assert estimate["invoice_subtotal_cents"] == 105625, "the estimate rounds once, to 105625"
    fx.inspect_job(sc, sample_size=500, defect_count=6)

    job = validate_success(
        sc.client.deliver_print_job(sc.job_id, f.deliver_payload(_split_manifest()),
                                    sc.vendor_headers), 200)

    asserts.assert_fields_equal(
        job,
        {
            "invoice_basis": INVOICE_FINAL,
            "invoice_subtotal_cents": 105624,
            "freight_cents": 45000,
            "defect_credit_cents": 1267,
            "invoice_total_cents": 149357,
            "delivered_quantity": 12500,
            "status": JOB_DELIVERED,
        },
        "print job")
    assert job["invoice_subtotal_cents"] == 105624, (
        "per-lot rounding bills 105624, exactly one cent under the 105625-cent estimate")


def test_dv_committed_print_total_moves_by_the_estimate_to_final_difference(client):
    """The election's committed print money falls from 150625 to 149357 cents on delivery.

    PRD Section 3.6: "Finally the election's `committed_print_cents` is adjusted by the difference between the new final total and the estimate total the job had previously contributed."

    Design: Difficulty/dual_variant_calc/dv_print_job_invoice_estimate_versus_final_rounding
    """
    sc = _locked_job_world(client)
    fx.printed_job(sc)
    assert sc.read_election()["committed_print_cents"] == 150625
    fx.inspect_job(sc, sample_size=500, defect_count=6)

    fx.deliver_job(sc, lots=_split_manifest())

    assert sc.read_election()["committed_print_cents"] == 149357, (
        "the committed total is adjusted by 149357 - 150625 = -1268 cents")


def test_dv_delivery_manifest_creates_one_lot_per_pallet_in_lot_code_order(client):
    """The three manifest lines become three in-transit lots of 4001, 4001 and 4498.

    PRD Section 3.6: "An accepted manifest moves the job `QC_PASSED → DELIVERED` and creates one ballot lot per line, each in `IN_TRANSIT` with `lot_code`, `quantity_shipped` and `seal_number` copied from the line, `election_id` copied from the job, and every accounting figure at rest: `quantity_received` 0, `issued_quantity` 0, `unused_quantity` 0, `voted_quantity` 0, `spoiled_quantity` 0, `returned_unused_quantity` 0, `accounted_quantity` 0, `lot_variance` 0, and `precinct_id` and `issued_by_user_id` null."

    Design: Difficulty/dual_variant_calc/dv_print_job_invoice_estimate_versus_final_rounding
    """
    sc = _locked_job_world(client)
    fx.printed_job(sc)
    fx.inspect_job(sc, sample_size=500, defect_count=6)
    fx.deliver_job(sc, lots=_split_manifest())

    rows, meta = validate_paginated(
        sc.client.list_ballot_lots(users.CUSTODIAN,
                                   {"print_job_id": sc.job_id, "limit": 100}))

    assert meta["total_count"] == 3, "one lot per manifest line"
    assert [row["lot_code"] for row in rows] == [LOT_CODE_1, LOT_CODE_2, LOT_CODE_3]
    assert [row["quantity_shipped"] for row in rows] == [4001, 4001, 4498]
    assert [row["custody_state"] for row in rows] == [LOT_IN_TRANSIT] * 3
    assert [row["seal_number"] for row in rows] == [SEAL_1, SEAL_2, SEAL_3]


# ─── The accountability worksheet: paper returned versus paper still in the field ─

def test_dv_accountability_final_canvass_scopes_only_the_returned_lots(client):
    """Scoped to the two returned lots the worksheet balances on a net variance of 99.

    PRD Section 3.9: "The `FINAL_CANVASS` basis reconciles only lots physically returned: `custody_state` equal to `RETURNED`."

    Design: Difficulty/dual_variant_calc/dv_accountability_preliminary_versus_final_canvass_scope
    """
    sc, _lots = _three_lot_deployed_world(client)

    worksheet = _worksheet(sc, BASIS_FINAL_CANVASS)

    asserts.assert_accountability_worksheet(
        worksheet,
        {
            "basis": BASIS_FINAL_CANVASS,
            "lot_count": 2,
            "gross_issued": 5000,
            "allowance_bp": 25,
            "spoilage_credit": 12,
            "net_issued": 4988,
            "accounted": 4889,
            "gross_variance": 111,
            "net_variance": 99,
            "tolerance_bp": 200,
            "tolerance_ballots": 99,
            "ballot_accountability_status": ACCOUNTABILITY_BALANCED,
        })


def test_dv_accountability_preliminary_scope_admits_the_one_ballot_lot_still_issued(client):
    """The lot still in the field pushes gross to 5001, cuts the allowance to 15 bp and unbalances the election.

    PRD Section 3.9: "`allowance_bp` is the spoilage allowance in basis points, keyed on **gross**: 25 basis points when `gross_issued` is 5000 or fewer, otherwise 15 basis points."

    Design: Difficulty/dual_variant_calc/dv_accountability_preliminary_versus_final_canvass_scope
    """
    sc, _lots = _three_lot_deployed_world(client)

    worksheet = _worksheet(sc, BASIS_PRELIMINARY)

    asserts.assert_accountability_worksheet(
        worksheet,
        {
            "basis": BASIS_PRELIMINARY,
            "lot_count": 3,
            "gross_issued": 5001,
            "allowance_bp": 15,
            "spoilage_credit": 7,
            "net_issued": 4994,
            "accounted": 4889,
            "gross_variance": 112,
            "net_variance": 105,
            "tolerance_bp": 200,
            "tolerance_ballots": 99,
            "ballot_accountability_status": ACCOUNTABILITY_OUT_OF_BALANCE,
        })


def test_dv_accountability_bases_return_opposite_verdicts_on_identical_stored_data(client):
    """One ballot of scope difference flips the verdict from balanced to out of balance.

    PRD Section 3.9: "`ballot_accountability_status` is `BALANCED` when the absolute value of `net_variance` is less than or equal to `tolerance_ballots`, and `OUT_OF_BALANCE` otherwise."

    Design: Difficulty/dual_variant_calc/dv_accountability_preliminary_versus_final_canvass_scope
    """
    sc, _lots = _three_lot_deployed_world(client)

    final = _worksheet(sc, BASIS_FINAL_CANVASS)
    preliminary = _worksheet(sc, BASIS_PRELIMINARY)

    assert final["ballot_accountability_status"] == ACCOUNTABILITY_BALANCED
    assert preliminary["ballot_accountability_status"] == ACCOUNTABILITY_OUT_OF_BALANCE
    assert (final["gross_issued"], preliminary["gross_issued"]) == (5000, 5001)
    assert (final["allowance_bp"], preliminary["allowance_bp"]) == (25, 15)
    assert (final["net_variance"], preliminary["net_variance"]) == (99, 105)
    assert final["accounted"] == preliminary["accounted"] == 4889, (
        "the lot still in the field reports no counts, so it adds nothing to accounted")


def test_dv_accountability_reads_leave_the_election_ledger_untouched(client):
    """Both worksheet reads are pure: no reconciliation figure is written to the election.

    PRD Section 3.9: "Because this read is not phase-gated it can be consulted at any point during the election as a running accountability check, and it applies no completeness rule — the read under `FINAL_CANVASS` simply narrows the lot scope rather than refusing."

    Design: Difficulty/dual_variant_calc/dv_accountability_preliminary_versus_final_canvass_scope
    """
    sc, _lots = _three_lot_deployed_world(client)
    version_before = sc.election_version()

    _worksheet(sc, BASIS_FINAL_CANVASS)
    _worksheet(sc, BASIS_PRELIMINARY)

    election = sc.read_election()
    asserts.assert_fields_equal(
        election,
        {
            "status": PHASE_DEPLOYED,
            "ballot_accountability_status": ACCOUNTABILITY_PENDING,
            "net_ballot_variance": 0,
            "reconciliation_basis": None,
            "last_reconciled_at": None,
            "version": version_before,
        },
        "election")


def test_dv_lot_accounted_quantities_are_what_the_two_scopes_disagree_about(client):
    """The two returned lots account 2950 and 1939 while the issued lot accounts nothing.

    PRD Section 3.9: "A lot still in `ISSUED` has not reported its counts, so it contributes 0 to `accounted` while contributing its full `issued_quantity` to `gross_issued`."

    Design: Difficulty/dual_variant_calc/dv_accountability_preliminary_versus_final_canvass_scope
    """
    sc, (lot_one, lot_two, lot_three) = _three_lot_deployed_world(client)

    first = sc.read_lot(lot_one)
    second = sc.read_lot(lot_two)
    third = sc.read_lot(lot_three)

    asserts.assert_fields_equal(
        first, {"custody_state": LOT_RETURNED, "accounted_quantity": 2950,
                "issued_quantity": 3000, "lot_variance": 50}, "lot L-001")
    asserts.assert_fields_equal(
        second, {"custody_state": LOT_RETURNED, "accounted_quantity": 1939,
                 "issued_quantity": 2000, "lot_variance": 61}, "lot L-002")
    asserts.assert_fields_equal(
        third, {"custody_state": LOT_ISSUED, "accounted_quantity": 0,
                "issued_quantity": 1}, "lot L-003")
