"""
Parental unilateral placement reimbursement: adjudication, remand and their exact
fiscal compensation.

A reimbursement claim reads no placement, no rate schedule and no attendance, so
a statutory day-rate ceiling stands in for a contract; the award basis decides
whether that ceiling binds, and remand must undo the disbursement cent for cent.
"""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_CONCURRENT_DISTRICT_PLACEMENT,
    ERR_EQUITABLE_FINDINGS_REQUIRED,
    ERR_INVALID_STATE_TRANSITION,
)
from test_helpers.assertions import assert_ledger
from test_helpers.fixtures import (
    adjudicate_claim,
    build_active_day_placement,
    file_claim,
    make_fiscal_account,
    make_student,
    read_account,
    read_claim,
    read_placement,
    read_student,
    reset_clock,
    set_clock,
    terminate_placement,
)
from test_helpers.test_users import (
    HEARING_ADJUDICATOR_HEADERS,
    make_parent_guardian_headers,
)

# ─── The shared claim: 4 500 000 tuition over 150 days, 200 000 transport ──────
AUTHORIZED_CENTS = 100000000
STATUTORY_CAP_CENTS = 4200000
STRICT_ELIGIBLE_CENTS = 4350000
EQUITABLE_ELIGIBLE_CENTS = 4650000
REDUCTION_PCT = 0.40
STRICT_TUITION_AWARD_CENTS = 2520000
EQUITABLE_TUITION_AWARD_CENTS = 2700000
TRANSPORT_AWARD_CENTS = 90000
STRICT_AWARD_CENTS = 2610000
EQUITABLE_AWARD_CENTS = 2790000
BASIS_GAP_CENTS = 180000
BOTH_AWARDS_CENTS = 5400000
AVAILABLE_AFTER_BOTH_CENTS = 94600000
AVAILABLE_AFTER_STRICT_CENTS = 97390000
AVAILABLE_AFTER_EQUITABLE_CENTS = 97210000

EQUITABLE_FINDINGS = (
    "District offer was not reasonably calculated to confer benefit on these "
    "communication goals."
)
SECOND_FINDINGS = (
    "District offer was materially inadequate and the parent cooperated "
    "throughout the process."
)
SHORT_FINDINGS = "Offer was inadequate."

# ─── The unclipped claim that reaches AWARDED_FULL ────────────────────────────
FULL_CLAIM = {
    "unilateral_school_name": "Ashfield Day School",
    "claimed_tuition_cents": 4000000,
    "claimed_transport_cents": 100000,
    "claimed_instructional_days": 200,
    "notice_date": "2026-08-20",
    "prior_district_offer_date": None,
}
FULL_ELIGIBLE_CENTS = 4100000
FULL_AWARD_CENTS = 4100000
FULL_TUITION_AWARD_CENTS = 4000000
FULL_TRANSPORT_AWARD_CENTS = 100000
AVAILABLE_AFTER_FULL_CENTS = 95900000

# ─── The concurrent district placement ────────────────────────────────────────
DAY_CONTRACT_ENCUMBRANCE_CENTS = 5760000
OVERLAPPING_WINDOW = {
    "unilateral_school_name": "Beacon Hill Learning Collaborative",
    "unilateral_start_date": "2026-09-01",
    "unilateral_end_date": "2027-06-15",
}
HEARING_INSTANT = "2027-01-15T09:00:00Z"


def _filed_claim_ref(api, **claim_overrides):
    """A funded account, a student with no district placement, and one FILED claim."""
    reset_clock(api)
    account = make_fiscal_account(api)
    student = make_student(api, state_student_id="SS-C017", full_name="Mira Oyelaran")
    ref = {
        "account": account,
        "student": student,
        "parent_headers": make_parent_guardian_headers(student["id"]),
    }
    ref["claim"] = file_claim(api, ref, **claim_overrides)
    return ref


class TestAwardBasisFork:
    """The award basis decides whether the statutory day-rate ceiling binds."""

    def test_the_strict_basis_trims_the_tuition_to_the_statutory_ceiling(self, api):
        """
        A 4 500 000 tuition claim over 150 days sits above the 28 000-per-day
        ceiling, so the eligible base is the ceiling plus the capped transport
        before the 40% reduction runs.

        PRD: "Under the `strict_statutory` basis the eligible tuition is the lesser of `claimed_tuition_cents` and that cap, so a claim whose implied per-day cost exceeds the ceiling is trimmed before any reduction runs."

        Design: Difficulty/dual_variant_calc/reimbursement_strict_statutory_versus_equitable_actual_cost
        """
        ref = _filed_claim_ref(api)
        filed = ref["claim"]
        assert filed["status"] == "FILED"
        assert filed["award_basis"] is None
        assert filed["awarded_amount_cents"] == 0
        assert filed["remand_round"] == 0

        awarded = adjudicate_claim(api, filed["id"], "strict_statutory")
        assert awarded["award_basis"] == "strict_statutory"
        assert awarded["equitable_reduction_pct"] == pytest.approx(REDUCTION_PCT)
        assert awarded["eligible_amount_cents"] == STRICT_ELIGIBLE_CENTS
        assert awarded["eligible_amount_cents"] == STATUTORY_CAP_CENTS + 150000
        assert awarded["awarded_tuition_cents"] == STRICT_TUITION_AWARD_CENTS
        assert awarded["awarded_transport_cents"] == TRANSPORT_AWARD_CENTS
        assert awarded["awarded_amount_cents"] == STRICT_AWARD_CENTS
        assert awarded["status"] == "AWARDED_PARTIAL"

        assert_ledger(
            read_account(api, ref["account"]["id"]),
            available=AVAILABLE_AFTER_STRICT_CENTS,
            encumbered=0,
            disbursed=STRICT_AWARD_CENTS,
        )

    def test_the_equitable_basis_waives_the_ceiling_on_identical_claim_data(self, api):
        """
        Two claims carrying byte-identical figures diverge by 180 000 cents once
        the hearing officer waives the tuition ceiling; the transport cap still
        binds on both.

        PRD: "Under the `equitable_actual_cost` basis the statutory ceiling is waived and the eligible tuition is the full `claimed_tuition_cents` — the hearing officer has found the district's own offer inadequate."

        Design: Difficulty/dual_variant_calc/reimbursement_strict_statutory_versus_equitable_actual_cost
        """
        ref = _filed_claim_ref(api)
        claim_a = ref["claim"]
        claim_b = file_claim(api, ref)

        strict = adjudicate_claim(api, claim_a["id"], "strict_statutory")
        equitable = adjudicate_claim(
            api,
            claim_b["id"],
            "equitable_actual_cost",
            equitable_findings=EQUITABLE_FINDINGS,
        )

        assert equitable["equitable_reduction_pct"] == pytest.approx(REDUCTION_PCT)
        assert equitable["eligible_amount_cents"] == EQUITABLE_ELIGIBLE_CENTS
        assert equitable["awarded_tuition_cents"] == EQUITABLE_TUITION_AWARD_CENTS
        assert equitable["awarded_transport_cents"] == TRANSPORT_AWARD_CENTS
        assert equitable["awarded_amount_cents"] == EQUITABLE_AWARD_CENTS
        assert equitable["status"] == "AWARDED_PARTIAL"

        assert (
            equitable["awarded_amount_cents"] - strict["awarded_amount_cents"]
        ) == BASIS_GAP_CENTS

        assert_ledger(
            read_account(api, ref["account"]["id"]),
            available=AVAILABLE_AFTER_BOTH_CENTS,
            encumbered=0,
            disbursed=BOTH_AWARDS_CENTS,
        )


def _overlapping_world(api):
    """An ACTIVE district placement and a claim covering exactly the same weeks."""
    world = build_active_day_placement(api)
    set_clock(api, HEARING_INSTANT)
    world["claim"] = file_claim(api, world, **OVERLAPPING_WINDOW)
    return world


class TestConcurrentPlacementBar:
    """Adjudication legality turns on a placement the claim never points at."""

    def test_an_active_overlapping_placement_bars_the_award(self, api):
        """
        The district will not pay a contracted school and reimburse the family for
        the same weeks, and the refusal leaves the claim and the ledger untouched.

        PRD: "Also at rung 12, the concurrent-placement bar: no `Placement` for the same student may be in `ACTIVE` status with a closed interval from its `start_date` to its `end_date` that intersects the claim's closed interval from `unilateral_start_date` to `unilateral_end_date`, or the call is refused with `ERR_CONCURRENT_DISTRICT_PLACEMENT` — the district will not simultaneously pay a contracted school for a seat and reimburse a parent for the same weeks."

        Design: Difficulty/cross_entity_state_dependency/reimbursement_adjudication_barred_by_overlapping_active_placement
        """
        world = _overlapping_world(api)

        response = api.adjudicate_reimbursement_claim(
            world["claim"]["id"],
            f.adjudicate_payload("strict_statutory"),
            HEARING_ADJUDICATOR_HEADERS,
        )
        validate_error(response, ERR_CONCURRENT_DISTRICT_PLACEMENT, 409)

        stored = read_claim(api, world["claim"]["id"])
        assert stored["status"] == "FILED"
        assert stored["award_basis"] is None
        assert stored["awarded_amount_cents"] == 0
        assert stored["eligible_amount_cents"] == 0

        assert_ledger(
            read_account(api, world["account"]["id"]),
            available=AUTHORIZED_CENTS - DAY_CONTRACT_ENCUMBRANCE_CENTS,
            encumbered=DAY_CONTRACT_ENCUMBRANCE_CENTS,
            disbursed=0,
        )

    def test_terminating_the_placement_unblocks_the_same_call(self, api):
        """
        Once the district placement is TERMINATED and its commitment released, the
        identical adjudication succeeds at the strict statutory figures.

        PRD: "Otherwise the claim is `AWARDED_PARTIAL`, which is the case whenever a reduction applied or the eligible base came in below the claimed total."

        Design: Difficulty/cross_entity_state_dependency/reimbursement_adjudication_barred_by_overlapping_active_placement
        """
        world = _overlapping_world(api)
        placement_id = world["placement"]["id"]

        terminate_placement(
            api,
            placement_id,
            reason=(
                "Parent maintained the unilateral placement; district placement "
                "closed."
            ),
        )
        assert read_placement(api, placement_id)["status"] == "TERMINATED"
        assert_ledger(
            read_account(api, world["account"]["id"]),
            available=AUTHORIZED_CENTS,
            encumbered=0,
            disbursed=0,
        )

        awarded = validate_success(
            api.adjudicate_reimbursement_claim(
                world["claim"]["id"],
                f.adjudicate_payload("strict_statutory"),
                HEARING_ADJUDICATOR_HEADERS,
            )
        )
        assert awarded["status"] == "AWARDED_PARTIAL"
        assert awarded["equitable_reduction_pct"] == pytest.approx(REDUCTION_PCT)
        assert awarded["eligible_amount_cents"] == STRICT_ELIGIBLE_CENTS
        assert awarded["awarded_tuition_cents"] == STRICT_TUITION_AWARD_CENTS
        assert awarded["awarded_transport_cents"] == TRANSPORT_AWARD_CENTS
        assert awarded["awarded_amount_cents"] == STRICT_AWARD_CENTS

        assert_ledger(
            read_account(api, world["account"]["id"]),
            available=AVAILABLE_AFTER_STRICT_CENTS,
            encumbered=0,
            disbursed=STRICT_AWARD_CENTS,
        )
        assert read_student(api, world["student"]["id"])["placement_status"] == (
            "TERMINATED"
        )


class TestAwardedFullIsTerminal:
    """The only terminal award state refuses remand and reverses nothing."""

    def test_remanding_an_awarded_full_claim_is_refused_and_moves_no_money(self, api):
        """
        A claim that got every cent it asked for cannot be reopened, and the
        refused remand must not run the compensating reversal.

        PRD: "A `HearingAdjudicator` may remand a claim in `AWARDED_PARTIAL` or `DENIED` status for re-adjudication, supplying a `remand_reason`."

        Design: Corner/state_machines/awarded_full_claim_is_terminal_and_rejects_remand
        """
        ref = _filed_claim_ref(api, **FULL_CLAIM)
        awarded = adjudicate_claim(api, ref["claim"]["id"], "strict_statutory")
        assert awarded["status"] == "AWARDED_FULL"
        assert awarded["eligible_amount_cents"] == FULL_ELIGIBLE_CENTS
        assert awarded["awarded_tuition_cents"] == FULL_TUITION_AWARD_CENTS
        assert awarded["awarded_transport_cents"] == FULL_TRANSPORT_AWARD_CENTS
        assert awarded["awarded_amount_cents"] == FULL_AWARD_CENTS
        assert awarded["equitable_reduction_pct"] == pytest.approx(0)

        response = api.remand_reimbursement_claim(
            ref["claim"]["id"],
            f.remand_payload(
                "District seeks reconsideration of the equitable factors."
            ),
            HEARING_ADJUDICATOR_HEADERS,
        )
        validate_error(response, ERR_INVALID_STATE_TRANSITION, 409)

        stored = read_claim(api, ref["claim"]["id"])
        assert stored["status"] == "AWARDED_FULL"
        assert stored["remand_round"] == 0
        assert stored["awarded_amount_cents"] == FULL_AWARD_CENTS

        assert_ledger(
            read_account(api, ref["account"]["id"]),
            available=AVAILABLE_AFTER_FULL_CENTS,
            encumbered=0,
            disbursed=FULL_AWARD_CENTS,
        )


class TestRemandCompensation:
    """Remand restores the pre-adjudication decomposition, not merely the sum."""

    def test_remand_reverses_the_disbursement_and_permits_readjudication(self, api):
        """
        The reversal returns the account to its opening decomposition, zeroes every
        award column, and leaves the claim adjudicable on the other basis for a
        different figure.

        PRD: "This is the compensating action for the adjudication disbursement and it must restore the ledger cent for cent: the fiscal account has `disbursed_cents` decreased by the claim's `awarded_amount_cents` and `available_cents` increased by exactly the same figure, with its `version` incremented, so the conservation identity of §2.6 returns to its pre-adjudication decomposition rather than merely still summing correctly."

        Design: Corner/state_machines/remand_compensates_the_disbursement_and_permits_readjudication
        """
        ref = _filed_claim_ref(api)
        claim_id = ref["claim"]["id"]
        awarded = adjudicate_claim(api, claim_id, "strict_statutory")
        assert awarded["status"] == "AWARDED_PARTIAL"
        assert awarded["awarded_amount_cents"] == STRICT_AWARD_CENTS
        assert_ledger(
            read_account(api, ref["account"]["id"]),
            available=AVAILABLE_AFTER_STRICT_CENTS,
            encumbered=0,
            disbursed=STRICT_AWARD_CENTS,
        )

        remanded = validate_success(
            api.remand_reimbursement_claim(
                claim_id,
                f.remand_payload(
                    "Hearing officer must weigh the equitable actual-cost basis."
                ),
                HEARING_ADJUDICATOR_HEADERS,
            )
        )
        assert remanded["status"] == "REMANDED"
        assert remanded["remand_round"] == 1
        assert remanded["award_basis"] is None
        assert remanded["awarded_amount_cents"] == 0
        assert remanded["awarded_tuition_cents"] == 0
        assert remanded["awarded_transport_cents"] == 0
        assert remanded["eligible_amount_cents"] == 0
        assert remanded["equitable_reduction_pct"] == pytest.approx(0)
        assert_ledger(
            read_account(api, ref["account"]["id"]),
            available=AUTHORIZED_CENTS,
            encumbered=0,
            disbursed=0,
        )

        readjudicated = adjudicate_claim(
            api,
            claim_id,
            "equitable_actual_cost",
            equitable_findings=SECOND_FINDINGS,
        )
        assert readjudicated["status"] == "AWARDED_PARTIAL"
        assert readjudicated["eligible_amount_cents"] == EQUITABLE_ELIGIBLE_CENTS
        assert readjudicated["equitable_reduction_pct"] == pytest.approx(REDUCTION_PCT)
        assert readjudicated["awarded_tuition_cents"] == (
            EQUITABLE_TUITION_AWARD_CENTS
        )
        assert readjudicated["awarded_transport_cents"] == TRANSPORT_AWARD_CENTS
        assert readjudicated["awarded_amount_cents"] == EQUITABLE_AWARD_CENTS
        assert readjudicated["remand_round"] == 1
        assert_ledger(
            read_account(api, ref["account"]["id"]),
            available=AVAILABLE_AFTER_EQUITABLE_CENTS,
            encumbered=0,
            disbursed=EQUITABLE_AWARD_CENTS,
        )


class TestEquitableFindingsGate:
    """The findings gate runs before the award arithmetic, not after it."""

    @pytest.mark.parametrize(
        "findings",
        [None, SHORT_FINDINGS],
        ids=["omitted", "twenty_one_characters"],
    )
    def test_the_equitable_basis_without_sufficient_findings_is_refused(
        self, api, findings
    ):
        """
        Neither an omitted nor a too-short set of findings supports the equitable
        basis, and after each refusal the claim is still FILED with no money moved.

        PRD: "At rung 12, the equitable-basis gate: an `award_basis` of `equitable_actual_cost` requires `equitable_findings` whose trimmed length is at least 30 characters, or the call is refused with `ERR_EQUITABLE_FINDINGS_REQUIRED`; under `strict_statutory` the field is ignored entirely and may be omitted or blank."

        Design: Corner/validations/equitable_adjudication_without_sufficient_findings_rejected
        """
        ref = _filed_claim_ref(api)
        payload = f.adjudicate_payload("equitable_actual_cost")
        if findings is not None:
            payload["equitable_findings"] = findings

        response = api.adjudicate_reimbursement_claim(
            ref["claim"]["id"], payload, HEARING_ADJUDICATOR_HEADERS
        )
        validate_error(response, ERR_EQUITABLE_FINDINGS_REQUIRED, 409)

        stored = read_claim(api, ref["claim"]["id"])
        assert stored["status"] == "FILED"
        assert stored["award_basis"] is None
        assert stored["awarded_amount_cents"] == 0
        assert stored["version"] == 1

        assert_ledger(
            read_account(api, ref["account"]["id"]),
            available=AUTHORIZED_CENTS,
            encumbered=0,
            disbursed=0,
        )
