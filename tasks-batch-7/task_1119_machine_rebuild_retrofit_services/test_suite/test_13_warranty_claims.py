"""Warranty claims: the strictly-greater drift tolerance boundary, the
temporal gate after an open claim blocks the close sweep, the state gate
beating the temporal gate, one-open-claim aggregate, and adjudication states."""

from datetime import datetime

import pytest

import test_helpers as fx
from test_helpers import (
    WARRANTY_ADMIN,
    ApiErrorId,
    make_customer_headers,
    validate_error,
    validate_success,
)

DELIVERY_CLOCK = "2026-06-01T00:00:00Z"
PAST_WARRANTY_CLOCK = "2027-07-01T00:00:00Z"
# accepted_positioning_microns of the standard PASS recording [8,-8,8,-8,0].
ACCEPTED_POSITIONING = 8.0


def _parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant; PRD pins the stamped instant (§3.8:
    "stamps `filed_at` from the logical clock at filing") but not its
    serialization format, so comparisons are by instant, not by string."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class TestWarrantyDriftBoundary:
    def test_drift_exactly_15_rejected(self, api):
        """PRD §3.8: "The drift gate then computes `drift_microns` as the filed `measured_positioning_microns` minus the project's `accepted_positioning_microns`, rounded half-up to two decimal places, and admits the claim only when the drift strictly exceeds 15.0 microns — a drift of exactly 15.0 is within tolerance and is rejected with `ERR_DRIFT_WITHIN_TOLERANCE`."

        Design: Difficulty/boundary_precision_check/warranty_drift_exactly_15_rejected
        """
        ctx = fx.setup_project_delivered(decision="MECHANICAL_REBUILD",
                                         delivery_clock=DELIVERY_CLOCK)
        # 23.0 - 8.0 = 15.0 exactly -> within tolerance -> rejected.
        res = api.create_warranty_claim(
            ctx.project["id"],
            {"claim_type": "ACCURACY_DRIFT", "measured_positioning_microns": 23.0},
            make_customer_headers(ctx.customer["id"]),
        )
        validate_error(res, ApiErrorId.ERR_DRIFT_WITHIN_TOLERANCE.value)

    def test_drift_just_above_15_admitted(self, api):
        """PRD §3.8: "The drift gate then computes `drift_microns` as the filed `measured_positioning_microns` minus the project's `accepted_positioning_microns`, rounded half-up to two decimal places, and admits the claim only when the drift strictly exceeds 15.0 microns — a drift of exactly 15.0 is within tolerance and is rejected with `ERR_DRIFT_WITHIN_TOLERANCE`."
        PRD §3.8: "The server stamps `filed_at` from the logical clock at filing."

        Design: Difficulty/boundary_precision_check/warranty_drift_exactly_15_rejected
        """
        ctx = fx.setup_project_delivered(decision="MECHANICAL_REBUILD",
                                         delivery_clock=DELIVERY_CLOCK)
        # 23.1 - 8.0 = 15.1 > 15.0 -> admissible.
        claim = fx.file_claim(ctx.project["id"], ctx.customer["id"],
                              claim_type="ACCURACY_DRIFT", measured_positioning_microns=23.1)
        assert claim["status"] == "FILED"
        assert claim["drift_microns"] == pytest.approx(15.1, abs=0.001)
        assert _parse_iso(claim["filed_at"]) == _parse_iso(DELIVERY_CLOCK)
        fx.assert_warranty_claim(claim)


class TestWarrantyClaimStateBeatsTemporal:
    def test_clock_sweep_closes_project_past_warranty_end(self, api):
        """PRD §2.7: "Second, every rebuild project in `WARRANTY_ACTIVE` whose `warranty_end` lies strictly before the new clock instant is swept to `CLOSED`, unless a warranty claim of that project is currently `FILED` or `APPROVED`, in which case the project remains under warranty administration."
        PRD §3.8: "Delivery stamps `delivery_date` from the logical clock, computes `warranty_end` as `delivery_date` plus `warranty_months` calendar months landing on the same day-of-month — where `warranty_months` is 6 for `RETROFIT_ONLY`, 12 for `MECHANICAL_REBUILD`, and 24 for `FULL_REBUILD` per the decision — moves the machine from `IN_PROJECT` to the terminal `RETURNED`, and moves `work_status` to `WARRANTY_ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/warranty_claim_state_beats_temporal
        """
        ctx = fx.setup_project_delivered(decision="MECHANICAL_REBUILD",
                                         delivery_clock=DELIVERY_CLOCK)
        assert ctx.project["warranty_end"] == "2027-06-01" + ctx.project["delivery_date"][10:]
        assert ctx.project["work_status"] == "WARRANTY_ACTIVE"

        fx.set_clock(PAST_WARRANTY_CLOCK)  # 2027-07-01, strictly past warranty_end
        project = fx.get_project(ctx.project["id"])
        assert project["work_status"] == "CLOSED"

    def test_claim_on_closed_project_reports_state_not_temporal(self, api):
        """PRD §2.8: "Every request passes through a fixed cascade of validation gates, evaluated in the order below. When several gates would fail, the earliest failing gate's error is the one reported, so higher-priority failures are never masked by lower-priority ones."
        PRD §3.8: "Filing against a project in any other state is rejected with `ERR_PROJECT_NOT_IN_WARRANTY`, and only one claim may be open at a time — filing while another claim of the same project is `FILED` or `APPROVED` is rejected with `ERR_CLAIM_ALREADY_OPEN`."

        Design: Difficulty/priority_pair_validation_conflict/warranty_claim_state_beats_temporal
        """
        ctx = fx.setup_project_delivered(decision="MECHANICAL_REBUILD",
                                         delivery_clock=DELIVERY_CLOCK)
        fx.set_clock(PAST_WARRANTY_CLOCK)
        assert fx.get_project(ctx.project["id"])["work_status"] == "CLOSED"

        # The filing violates both the state gate (project CLOSED) and the
        # temporal gate (clock past warranty_end); the state gate is earlier.
        res = api.create_warranty_claim(
            ctx.project["id"],
            {"claim_type": "ACCURACY_DRIFT", "measured_positioning_microns": 30.0},
            make_customer_headers(ctx.customer["id"]),
        )
        validate_error(res, ApiErrorId.ERR_PROJECT_NOT_IN_WARRANTY.value)


def test_warranty_expired_temporal_after_open_claim_blocks_sweep(api):
    """PRD §2.7: "Second, every rebuild project in `WARRANTY_ACTIVE` whose `warranty_end` lies strictly before the new clock instant is swept to `CLOSED`, unless a warranty claim of that project is currently `FILED` or `APPROVED`, in which case the project remains under warranty administration."
    PRD §3.8: "The temporal gate requires the filing clock to be no later than the project's `warranty_end`; filing strictly after the end is rejected with `ERR_WARRANTY_EXPIRED`, while filing at exactly the end instant remains admissible."
    PRD §3.8: "A filed claim may be approved, moving `FILED` to `APPROVED`, or rejected, moving `FILED` to the terminal `REJECTED`; an approved claim is later closed by a remediate write, moving `APPROVED` to the terminal `CLOSED`."

    Design: Corner/validations/warranty_expired_temporal_after_open_claim_blocks_sweep
    """
    ctx = fx.setup_project_delivered(decision="MECHANICAL_REBUILD",
                                     delivery_clock=DELIVERY_CLOCK)
    claim = fx.file_claim(ctx.project["id"], ctx.customer["id"],
                          claim_type="ACCURACY_DRIFT", measured_positioning_microns=30.0)
    assert claim["status"] == "FILED"

    # The sweep at 2027-07-01 leaves the project WARRANTY_ACTIVE: the claim is open.
    fx.set_clock(PAST_WARRANTY_CLOCK)
    assert fx.get_project(ctx.project["id"])["work_status"] == "WARRANTY_ACTIVE"

    fx.adjudicate_claim(claim["id"], "approve")
    closed = fx.adjudicate_claim(claim["id"], "remediate", notes="re-aligned on site")
    assert closed["status"] == "CLOSED"

    # Still WARRANTY_ACTIVE (no new sweep ran), so the state gate passes and the
    # filing fails at the temporal gate.
    assert fx.get_project(ctx.project["id"])["work_status"] == "WARRANTY_ACTIVE"
    res = api.create_warranty_claim(
        ctx.project["id"],
        {"claim_type": "ACCURACY_DRIFT", "measured_positioning_microns": 30.0},
        make_customer_headers(ctx.customer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_WARRANTY_EXPIRED.value)


def test_claim_already_open_rejected(api):
    """PRD §3.8: "Filing against a project in any other state is rejected with `ERR_PROJECT_NOT_IN_WARRANTY`, and only one claim may be open at a time — filing while another claim of the same project is `FILED` or `APPROVED` is rejected with `ERR_CLAIM_ALREADY_OPEN`."

    Design: Corner/validations/claim_already_open_rejected
    """
    ctx = fx.setup_project_delivered(decision="MECHANICAL_REBUILD",
                                     delivery_clock=DELIVERY_CLOCK)
    first = fx.file_claim(ctx.project["id"], ctx.customer["id"],
                          claim_type="ACCURACY_DRIFT", measured_positioning_microns=30.0)
    assert first["status"] == "FILED"

    res = api.create_warranty_claim(
        ctx.project["id"], {"claim_type": "MECHANICAL_DEFECT"},
        make_customer_headers(ctx.customer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_CLAIM_ALREADY_OPEN.value)


def test_claim_approve_twice_rejected(api):
    """PRD §3.8: "A filed claim may be approved, moving `FILED` to `APPROVED`, or rejected, moving `FILED` to the terminal `REJECTED`; an approved claim is later closed by a remediate write, moving `APPROVED` to the terminal `CLOSED`."
    PRD §2.8: "The target entity is in the state the action requires per its state machine; otherwise one of `ERR_INVALID_STATE`, `ERR_PROJECT_NOT_IN_WARRANTY`, `ERR_COMMERCIAL_NOT_APPROVED`, `ERR_QUOTE_REQUIRED`, or `ERR_PROJECT_NOT_AWAITING_ACCEPTANCE` (HTTP 409)."

    Design: Corner/state_machines/claim_approve_twice_rejected
    """
    ctx = fx.setup_project_delivered(decision="MECHANICAL_REBUILD",
                                     delivery_clock=DELIVERY_CLOCK)
    claim = fx.file_claim(ctx.project["id"], ctx.customer["id"],
                          claim_type="MECHANICAL_DEFECT")
    approved = fx.adjudicate_claim(claim["id"], "approve")
    assert approved["status"] == "APPROVED"

    res = api.approve_claim(claim["id"], {}, WARRANTY_ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    after = validate_success(api.get_warranty_claim(claim["id"], WARRANTY_ADMIN), 200)
    assert after["status"] == "APPROVED"
