"""Core purchase batches: sorting gates, settlement, and terminal lockdown."""
import pytest

from test_helpers import (
    PRO,
    YARD,
    ApiErrorId,
    api_client,
    begin_sorting,
    close_batch,
    create_core_batch,
    create_core_unit_payload,
    create_sorting_batch_with_cores,
    finish_sorting,
    get_batch,
    get_core,
    receive_core,
    setup_batch_in_audit,
    sort_core,
    validate_error,
    validate_success,
)


def _setup_settlement_batch():
    """9 sorted cores (4 A, 3 B, 2 SCRAP), manifest 10, batch in AUDIT."""
    batch, cores = create_sorting_batch_with_cores(
        supplier_name="CoreCo",
        agreed_unit_price_cents=500,
        manifest_count=10,
        estimated_grade_mix={"A": 0.5, "B": 0.3, "SCRAP": 0.2},
        num_cores=9)
    grades = ["A", "A", "A", "A", "B", "B", "B", "SCRAP", "SCRAP"]
    for core, grade in zip(cores, grades):
        note = "broken stringers" if grade == "SCRAP" else None
        sort_core(core["id"], grade, condition_notes=note)
    finish_sorting(batch["id"])
    return batch, cores


class TestSettlementDualVariant:

    def test_close_computes_final_settlement_with_grade_schedule_and_penalty(self):
        """PRD §3.3: "an `A` core earns the full `agreed_unit_price_cents` (a
        factor of 1.00), a `B` core earns six-tenths of `agreed_unit_price_cents`
        rounded half-up per unit, and a `SCRAP` core earns nothing."
        PRD §3.3: "If `received_count` falls short of `manifest_count`, an
        under-delivery penalty of the shortfall multiplied by
        `agreed_unit_price_cents` multiplied by one quarter, rounded half-up,
        is deducted, and the settlement is floored at zero cents."

        Design: Difficulty/dual_variant_calc/core_batch_provisional_vs_final_settlement
        """
        batch, _cores = _setup_settlement_batch()
        resp = api_client.close_batch(batch["id"], PRO)
        closed = validate_success(resp)
        assert closed["status"] == "CLOSED"
        # provisional pays the manifest claim: 10 * 500 = 5000
        assert closed["provisional_settlement_cents"] == 5000
        # final: 4*500 + 3*round(500*0.6) + 2*0 - round(1*500*0.25)
        #      = 2000 + 900 + 0 - 125 = 2775
        assert closed["final_settlement_cents"] == 2775, (
            f"final settlement must reflect grade mix and shortage penalty: "
            f"expected 2775, got {closed['final_settlement_cents']}"
        )
        assert closed["final_settlement_cents"] != \
            closed["provisional_settlement_cents"]

    def test_close_stamps_grade_yield_variance_and_retains_provisional(self):
        """PRD §3.3: "The same close stamps `grade_yield_variance_bp`: the
        actual `A`-grade fraction (the count of `A` cores divided by
        `received_count`) minus the supplier's estimated `A` fraction from
        `estimated_grade_mix`, the difference multiplied by ten thousand and
        rounded half-up to whole basis points."
        PRD §3.3: "Crucially, `provisional_settlement_cents` is retained at
        close — never zeroed — so procurement can report
        provisional-versus-final divergence, which appears whenever actual
        grades include `B` or `SCRAP` cores or the delivery ran short."

        Design: Difficulty/dual_variant_calc/core_batch_provisional_vs_final_settlement
        """
        batch, _cores = _setup_settlement_batch()
        closed = validate_success(api_client.close_batch(batch["id"], PRO))
        # actual A fraction = 4/9; estimated 0.5; (4/9 - 0.5) * 10000 = -556
        assert closed["grade_yield_variance_bp"] == -556, (
            f"expected grade_yield_variance_bp -556, "
            f"got {closed['grade_yield_variance_bp']}"
        )
        assert closed["received_count"] == 9
        assert closed["provisional_settlement_cents"] == 5000, (
            "provisional settlement must be retained (not zeroed) at close"
        )


class TestBatchStateGatesCores:

    def test_late_core_creation_against_audit_batch_rejected(self):
        """PRD §3.3: "Receiving is accepted only while the batch is `RECEIVING`
        or `SORTING`; against any other batch state it fails with
        `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/core_sort_gated_by_batch_state
        """
        batch, _cores = setup_batch_in_audit(
            supplier_name="GateCo", agreed_unit_price_cents=500,
            manifest_count=2,
            estimated_grade_mix={"A": 1.0, "B": 0.0, "SCRAP": 0.0},
            grades=("A", "A"))
        assert batch["status"] == "AUDIT"
        resp = api_client.create_core_unit(
            create_core_unit_payload(batch_id=batch["id"], species="PINE"),
            YARD,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409
        after = get_batch(batch["id"])
        assert after["status"] == "AUDIT"

    def test_late_core_creation_against_closed_batch_rejected(self):
        """PRD §3.3: "Receiving is accepted only while the batch is `RECEIVING`
        or `SORTING`; against any other batch state it fails with
        `ERR_INVALID_STATE`."
        PRD §3.3: "Closing the batch is a `ProcurementManager` act requiring
        `AUDIT` status (else `ERR_BATCH_NOT_AUDIT`), and it produces the final
        accounting."

        Design: Difficulty/cross_entity_state_dependency/core_sort_gated_by_batch_state
        """
        batch, _cores = setup_batch_in_audit(
            supplier_name="GateCo", agreed_unit_price_cents=500,
            manifest_count=2,
            estimated_grade_mix={"A": 1.0, "B": 0.0, "SCRAP": 0.0},
            grades=("A", "A"))
        closed = close_batch(batch["id"])
        assert closed["status"] == "CLOSED"
        resp = api_client.create_core_unit(
            create_core_unit_payload(batch_id=batch["id"], species="PINE"),
            YARD,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409
        after = get_batch(batch["id"])
        assert after["status"] == "CLOSED"


class TestBatchTerminalLockdown:

    def test_closed_batch_rejects_second_close(self):
        """PRD §3.3: "Closing the batch is a `ProcurementManager` act requiring
        `AUDIT` status (else `ERR_BATCH_NOT_AUDIT`), and it produces the final
        accounting."
        PRD §3.3: "The batch lifecycle runs `RECEIVING` → `SORTING` → `AUDIT` →
        `CLOSED`."

        Design: Corner/state_machines/terminal_state_lockdown_closed_batch
        """
        batch, _cores = setup_batch_in_audit(
            supplier_name="TermCo", agreed_unit_price_cents=500,
            manifest_count=1,
            estimated_grade_mix={"A": 1.0, "B": 0.0, "SCRAP": 0.0},
            grades=("A",))
        close_batch(batch["id"])
        resp = api_client.close_batch(batch["id"], PRO)
        validate_error(resp, ApiErrorId.ERR_BATCH_NOT_AUDIT)
        assert resp.status_code == 409
        after = get_batch(batch["id"])
        assert after["status"] == "CLOSED"


class TestSortGates:

    def test_sort_already_sorted_core_rejected(self):
        """PRD §3.3: "Sorting an individual core — a `YardSupervisor` action
        carrying a payload `grade` of `A`, `B`, or `SCRAP` and an optional
        `condition_notes` — requires the owning batch to be in `SORTING` (else
        `ERR_BATCH_NOT_SORTING`) and the core to still be `UNSORTED` (else
        `ERR_CORE_ALREADY_SORTED`)"

        Design: Corner/state_machines/invalid_transition_sort_already_sorted_core
        """
        batch, cores = create_sorting_batch_with_cores(
            supplier_name="TwiceCo", agreed_unit_price_cents=500,
            manifest_count=1,
            estimated_grade_mix={"A": 1.0, "B": 0.0, "SCRAP": 0.0})
        sort_core(cores[0]["id"], "A")
        resp = api_client.sort_core(cores[0]["id"], {"grade": "B"}, YARD)
        validate_error(resp, ApiErrorId.ERR_CORE_ALREADY_SORTED)
        assert resp.status_code == 409
        core = get_core(cores[0]["id"])
        assert core["grade"] == "A", (
            f"rejected re-sort must not change the grade, got {core['grade']}"
        )

    def test_scrap_sort_requires_condition_note(self):
        """PRD §3.3: "declaring a core `SCRAP` additionally demands a non-empty
        `condition_notes` explaining the condemnation, else
        `ERR_SCRAP_NOTE_REQUIRED`."

        Design: Corner/validations/scrap_sort_requires_condition_note
        """
        batch, cores = create_sorting_batch_with_cores(
            supplier_name="NoteCo", agreed_unit_price_cents=100,
            manifest_count=2,
            estimated_grade_mix={"A": 0.5, "B": 0.0, "SCRAP": 0.5},
            num_cores=2)
        resp = api_client.sort_core(cores[0]["id"], {"grade": "SCRAP"}, YARD)
        validate_error(resp, ApiErrorId.ERR_SCRAP_NOTE_REQUIRED)
        assert resp.status_code == 422
        core1 = get_core(cores[0]["id"])
        assert core1["grade"] == "UNSORTED", (
            "rejected SCRAP sort must leave the core UNSORTED"
        )
        # A-grade sorts do not require the note.
        core2 = sort_core(cores[1]["id"], "A")
        assert core2["grade"] == "A"

    def test_finish_sorting_with_unsorted_core_rejected(self):
        """PRD §3.3: "Finishing sorting moves the batch from `SORTING` to
        `AUDIT` and is blocked twice over: the batch must be `SORTING` (else
        `ERR_BATCH_NOT_SORTING`), and every core in the batch must have left
        `UNSORTED` behind — one lingering `UNSORTED` core rejects the
        transition with `ERR_CORES_UNSORTED`."

        Design: Corner/validations/finish_sorting_blocked_by_unsorted_cores
        """
        batch, cores = create_sorting_batch_with_cores(
            supplier_name="PartialCo", agreed_unit_price_cents=100,
            manifest_count=2,
            estimated_grade_mix={"A": 1.0, "B": 0.0, "SCRAP": 0.0},
            num_cores=2)
        sort_core(cores[0]["id"], "A")
        # cores[1] deliberately left UNSORTED
        resp = api_client.finish_sorting(batch["id"], YARD)
        validate_error(resp, ApiErrorId.ERR_CORES_UNSORTED)
        assert resp.status_code == 409
        after = get_batch(batch["id"])
        assert after["status"] == "SORTING", (
            f"blocked finish-sorting must leave the batch SORTING, "
            f"got {after['status']}"
        )
