"""Yield reconciliation basis, tolerance gate, OCC amendment, record-review SoD."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    get_batch,
    make_qa_manager_headers,
    setup_batch_at_stage,
    setup_two_completed_batches,
    validate_error,
    validate_success,
)

OPERATOR = TEST_USERS["production_operator_headers"]
QA = TEST_USERS["qa_manager_headers"]


class TestYieldVarianceBasis:
    def test_yield_variance_uses_finished_units_basis(self, api):
        """PRD §3.4: "On completion the system computes `yield_variance_pct`: the
        difference between `actual_yield_units` and the snapshotted
        `theoretical_units`, divided by `theoretical_units`, multiplied by one
        hundred, and rounded half-up to two decimal places."
        PRD §3.4: "The variance basis is pinned to finished units — the denominator
        is always the theoretical unit count, never a bulk-mass figure; a
        mass-based reconciliation is a documented alternative reading the system
        deliberately does not use".

        Design: Difficulty/dual_variant_calc/yield_units_vs_mass_basis
        """
        # theoretical 10000 units; nominal bulk 5000 g (500 mg x 10000).
        ctx = setup_batch_at_stage("COMPLETED", actual_yield=9600, actual_mass=4750)
        batch = ctx["batch"]
        assert batch["production_status"] == "COMPLETED"
        # Units basis: (9600 - 10000) / 10000 * 100 = -4.00.
        assert batch["yield_variance_pct"] == -4.0, (
            f"units-basis variance must be -4.00, got {batch['yield_variance_pct']}"
        )
        # Mass basis would read (4750 - 5000) / 5000 * 100 = -5.00 — rejected.
        assert batch["yield_variance_pct"] != -5.0

    def test_yield_variance_mass_basis_reading_rejected(self, api):
        """PRD §3.4: "The variance basis is pinned to finished units — the
        denominator is always the theoretical unit count, never a bulk-mass figure;
        a mass-based reconciliation is a documented alternative reading the system
        deliberately does not use, because the two diverge whenever measured bulk
        mass deviates from units times nominal unit mass."

        Design: Difficulty/dual_variant_calc/yield_units_vs_mass_basis
        """
        # Second datapoint: 9500 units (-5.00% units) vs 4500 g (-10.00% mass).
        ctx = setup_batch_at_stage("COMPLETED", actual_yield=9500, actual_mass=4500)
        batch = ctx["batch"]
        assert batch["yield_variance_pct"] == -5.0, (
            f"units-basis variance must be -5.00, got {batch['yield_variance_pct']}"
        )
        assert batch["yield_variance_pct"] != -10.0, (
            "the mass-basis reading must not leak into yield_variance_pct"
        )


class TestYieldToleranceGate:
    def test_record_review_tolerance_minus_10_inclusive(self, api):
        """PRD §3.5: "the yield tolerance gate applies — the absolute value of
        `yield_variance_pct` must be at most 10.0, with exactly 10.0 passing, and a
        breach rejected with `ERR_YIELD_VARIANCE_EXCEEDED`."

        Design: Corner/calculations/yield_tolerance_boundary_minus_10_inclusive
        """
        ctx, run1, run2 = setup_two_completed_batches(
            yields=(9000, 8999), masses=(4950, 4949.45)
        )
        b1 = run1["batch"]
        b2 = run2["batch"]
        # (9000 - 10000) / 10000 * 100 = -10.00; (8999 - 10000) / 10000 * 100 = -10.01.
        assert b1["yield_variance_pct"] == -10.0
        assert b2["yield_variance_pct"] == -10.01

        ok = api.record_review_batch(b1["id"], {}, QA)
        reviewed = validate_success(ok, 200)
        assert reviewed["production_status"] == "RECORD_REVIEWED", (
            "exactly -10.00 passes the inclusive tolerance gate"
        )

        breach = api.record_review_batch(b2["id"], {}, QA)
        validate_error(breach, ApiErrorId.ERR_YIELD_VARIANCE_EXCEEDED)
        assert breach.status_code == 409
        assert get_batch(b2["id"])["production_status"] == "COMPLETED"


class TestYieldAmendmentOcc:
    def test_stale_batch_amendment_rejected_412(self, api):
        """PRD §2.8: "An amendment of a completed batch's yield figures must
        likewise carry `expected_batch_version` matching the batch's current
        `version`; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412)".
        PRD §3.4: "a successful amendment recomputes `yield_variance_pct` from the
        amended figures and increments the batch's `version` by one."

        Design: Corner/cross_cutting_layers/batch_yield_amend_stale_version_412
        """
        ctx = setup_batch_at_stage("COMPLETED", actual_yield=9600, actual_mass=4750)
        batch = ctx["batch"]
        assert batch["yield_variance_pct"] == -4.0
        base_version = batch["version"]

        first = api.amend_batch(
            batch["id"],
            {"actual_yield_units": 9700, "actual_bulk_mass_g": 4800,
             "expected_batch_version": base_version},
            OPERATOR,
        )
        amended = validate_success(first, 200)
        assert amended["version"] == base_version + 1
        # (9700 - 10000) / 10000 * 100 = -3.00.
        assert amended["yield_variance_pct"] == -3.0

        stale = api.amend_batch(
            batch["id"],
            {"actual_yield_units": 9800, "actual_bulk_mass_g": 4850,
             "expected_batch_version": base_version},
            OPERATOR,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        assert stale.status_code == 412

        current = get_batch(batch["id"])
        assert current["actual_yield_units"] == 9700, (
            "the first amendment stands after the stale amendment is rejected"
        )
        assert current["yield_variance_pct"] == -3.0


class TestRecordReviewSod:
    def test_record_review_by_completing_user_rejected_sod(self, api):
        """PRD §3.5: "the reviewer must not be the operator in `recorded_by_id`
        (`ERR_SOD_VIOLATION`)".
        PRD §3.5: "A passing review moves the batch to `RECORD_REVIEWED` and records
        the reviewer in `reviewed_by_id`."

        Design: Corner/state_machines/record_review_by_completing_user_rejected_sod
        """
        ctx = setup_batch_at_stage("COMPLETED", op_id="shared-1")
        assert ctx["batch"]["recorded_by_id"] == "shared-1"

        same_user = api.record_review_batch(
            ctx["batch"]["id"], {}, make_qa_manager_headers("shared-1")
        )
        validate_error(same_user, ApiErrorId.ERR_SOD_VIOLATION)
        assert same_user.status_code == 403

        other_user = api.record_review_batch(
            ctx["batch"]["id"], {}, make_qa_manager_headers("qm-1")
        )
        reviewed = validate_success(other_user, 200)
        assert reviewed["production_status"] == "RECORD_REVIEWED"
        assert reviewed["reviewed_by_id"] == "qm-1"
