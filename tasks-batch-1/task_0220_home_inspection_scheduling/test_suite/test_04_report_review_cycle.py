"""The defect report: creation, the reject/revise revision loop, defect risk scoring
(provisional vs final), per-defect rounding, severity banding, and add-on uniqueness.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_inspector_headers,
    setup_requested_order, setup_started_order, setup_submitted_report,
)
from test_helpers import factories as F

SCHED = TEST_USERS["scheduler_headers"]


# ---------------------------------------------------------------------------
# report initial state
# ---------------------------------------------------------------------------
def test_new_report_is_draft_with_zero_provisional(api):
    """PRD §3.6: "The report is born in `DRAFT` with its `provisional_risk_score`
    initialized to 0, and creating it advances the owning order from `IN_PROGRESS` to
    `REPORT_DRAFT` while incrementing the order's `version`."

    Design: Corner/state_machines/corner_initial_state_report_is_draft
    """
    cfg, order = setup_started_order(inspection_type="BUYER", certifications=["BUYER"],
                                     scheduled_start="2026-08-03T13:00:00Z")
    insp_headers = make_inspector_headers(cfg["inspector"]["id"])
    resp = api.create_report(order["id"], F.create_report_payload(2200), insp_headers)
    report = validate_success(resp, 201)
    assert report["status"] == "DRAFT"
    assert report["provisional_risk_score"] == 0


# ---------------------------------------------------------------------------
# non-linear state machine: reject -> revise -> submit revision loop
# ---------------------------------------------------------------------------
def test_report_reject_revise_resubmit_cycle(api):
    """PRD §3.6: "A rejected report can be reopened for revision by the assigned
    inspector, which returns it from `REJECTED` to `DRAFT` and increments its `version`;
    the `REJECTED → DRAFT → SUBMITTED` loop may repeat as many times as needed."
    PRD §3.6: "Submitting a `DRAFT` report moves it to `SUBMITTED`."

    Design: Difficulty/non_linear_state_machine/report_reject_revise_cycle
    """
    cfg, order, report, _ = setup_submitted_report(
        inspection_type="BUYER", certifications=["BUYER"],
        scheduled_start="2026-07-04T13:00:00Z")
    insp_headers = make_inspector_headers(cfg["inspector"]["id"])
    get_success_data(api.reject_report(report["id"], SCHED))
    get_success_data(api.revise_report(report["id"], insp_headers))
    resubmitted = validate_success(api.submit_report(report["id"], insp_headers))
    assert resubmitted["status"] == "SUBMITTED"


def test_report_revision_loop_version_advances(api):
    """PRD §2.4: "`version`, an integer that begins at 1 and increments by one on every
    mutation of the resource."
    PRD §3.6: "Rejection moves a `SUBMITTED` report to `REJECTED` and increments its
    `version`. A rejected report can be reopened for revision by the assigned
    inspector, which returns it from `REJECTED` to `DRAFT` and increments its `version`."

    Design: Difficulty/non_linear_state_machine/report_reject_revise_cycle
    """
    cfg, order, report, _ = setup_submitted_report(
        inspection_type="BUYER", certifications=["BUYER"],
        scheduled_start="2026-07-04T13:00:00Z")
    insp_headers = make_inspector_headers(cfg["inspector"]["id"])
    # report: created v1 -> submit v2 (done in fixture)
    get_success_data(api.reject_report(report["id"], SCHED))      # v3
    get_success_data(api.revise_report(report["id"], insp_headers))  # v4
    resubmitted = validate_success(api.submit_report(report["id"], insp_headers))  # v5
    assert resubmitted["version"] == 5


# ---------------------------------------------------------------------------
# dual variant defect risk: provisional (all non-VOIDED) vs final (CONFIRMED only)
# ---------------------------------------------------------------------------
def test_provisional_vs_final_risk_score_diverge(api):
    """PRD §3.6: "The `provisional_risk_score`, computed at submission, ranges over
    every defect whose `status` is not `VOIDED` (the `LOGGED` defects plus any already
    `CONFIRMED` or `CLEARED`). The `final_risk_score`, computed at approval, ranges over
    only the `CONFIRMED` defects; because `MINOR` defects are `CLEARED` at approval, they
    are excluded from the final figure."
    PRD §3.6: "In practical terms a `MINOR` defect contributes 33 points, a `MAJOR`
    defect 133 points, and a `CRITICAL` defect 333 points."

    Design: Difficulty/dual_variant_calc/defect_risk_provisional_vs_final_on_report
    """
    # 2 MINOR + 1 MAJOR + 1 CRITICAL:
    #   provisional = 33+33+133+333 = 532
    #   final (CONFIRMED only = MAJOR+CRIT) = 133+333 = 466
    cfg, order, report, _ = setup_submitted_report(
        inspection_type="BUYER", certifications=["BUYER"],
        scheduled_start="2026-07-01T13:00:00Z",
        defects=[("Roof", "MINOR"), ("Porch", "MINOR"),
                 ("Panel", "MAJOR"), ("Foundation", "CRITICAL")])
    assert report["provisional_risk_score"] == 532
    approved = validate_success(api.approve_report(report["id"], SCHED))
    assert approved["final_risk_score"] == 466
    assert approved["final_risk_score"] != report["provisional_risk_score"]


def test_provisional_vs_final_risk_single_minor_cleared(api):
    """PRD §3.6: "the `final_risk_score`, computed at approval, ranges over only the
    `CONFIRMED` defects; because `MINOR` defects are `CLEARED` at approval, they are
    excluded from the final figure."
    PRD §3.6: "In practical terms a `MINOR` defect contributes 33 points, a `MAJOR`
    defect 133 points, and a `CRITICAL` defect 333 points."

    Design: Difficulty/dual_variant_calc/defect_risk_provisional_vs_final_on_report
    """
    # 1 MAJOR + 1 MINOR: provisional = 133 + 33 = 166; final (MAJOR only) = 133.
    cfg, order, report, _ = setup_submitted_report(
        inspection_type="BUYER", certifications=["BUYER"],
        scheduled_start="2026-07-28T13:00:00Z",
        defects=[("Panel", "MAJOR"), ("Roof", "MINOR")])
    assert report["provisional_risk_score"] == 166
    approved = validate_success(api.approve_report(report["id"], SCHED))
    assert approved["final_risk_score"] == 133
    assert approved["final_risk_score"] != report["provisional_risk_score"]


# ---------------------------------------------------------------------------
# per-item rounding then sum (NOT sum-then-round)
# ---------------------------------------------------------------------------
def test_per_defect_rounding_then_sum_three_minor(api):
    """PRD §3.6: "For each included defect, its weighted points are the defect's weight
    multiplied by 100 and divided by 3, rounded half up to an integer; these per-defect
    integers are then summed to form the score. This per-defect-then-sum order is fixed
    and is not the same as summing first and rounding once."
    PRD §3.6: "In practical terms a `MINOR` defect contributes 33 points."

    Design: Difficulty/combinatorial_formula/defect_score_per_item_rounding_then_sum_mode_b
    """
    # 3 MINOR: per-item round(100/3)=33 each -> 33+33+33 = 99, NOT round(3*100/3)=100.
    cfg, order, report, _ = setup_submitted_report(
        inspection_type="BUYER", certifications=["BUYER"],
        scheduled_start="2026-07-03T13:00:00Z",
        defects=[("Roof", "MINOR"), ("Porch", "MINOR"), ("Deck", "MINOR")])
    assert report["provisional_risk_score"] == 99


def test_per_defect_rounding_mixed_severity_provisional(api):
    """PRD §3.6: "For each included defect, its weighted points are the defect's weight
    multiplied by 100 and divided by 3, rounded half up to an integer; these per-defect
    integers are then summed to form the score. This per-defect-then-sum order is fixed
    and is not the same as summing first and rounding once."

    Design: Difficulty/combinatorial_formula/defect_score_per_item_rounding_then_sum_mode_b
    """
    # 1 MAJOR + 2 MINOR provisional: 133 + 33 + 33 = 199 (per-item), NOT
    # round((4+1+1)*100/3) = round(200) = 200 (sum-then-round).
    cfg, order, report, _ = setup_submitted_report(
        inspection_type="BUYER", certifications=["BUYER"],
        scheduled_start="2026-07-29T13:00:00Z",
        defects=[("Panel", "MAJOR"), ("Roof", "MINOR"), ("Porch", "MINOR")])
    assert report["provisional_risk_score"] == 199


# ---------------------------------------------------------------------------
# empty defect set -> PASS band at approval
# ---------------------------------------------------------------------------
def test_empty_defect_set_yields_pass_band(api):
    """PRD §3.6: "its `severity_band` — one of `PASS`, `MINOR`, `MAJOR`, or `CRITICAL`
    — is derived only at approval, taking `PASS` when there are zero defects."
    PRD §3.6: "A final score of exactly 0 yields `PASS`."

    Design: Difficulty/boundary_precision_check/empty_defect_set_yields_pass_band_on_approve
    """
    cfg, order, report, _ = setup_submitted_report(
        inspection_type="BUYER", certifications=["BUYER"],
        scheduled_start="2026-07-12T13:00:00Z", defects=[])
    approved = validate_success(api.approve_report(report["id"], SCHED))
    assert approved["final_risk_score"] == 0
    assert approved["severity_band"] == "PASS"


def test_single_major_defect_lands_on_major_floor(api):
    """PRD §3.6: "A score from 133 up to but not including 666 yields `MAJOR` — so a
    single confirmed `MAJOR` defect, at 133, lands exactly on the `MAJOR` floor."
    PRD §3.6: "The `severity_band` is read off the `final_risk_score` by integer
    thresholds, with each floor inclusive."

    Design: Difficulty/boundary_precision_check/empty_defect_set_yields_pass_band_on_approve
    """
    # 1 MAJOR defect -> CONFIRMED -> final 133 -> band MAJOR (floor inclusive).
    cfg, order, report, _ = setup_submitted_report(
        inspection_type="BUYER", certifications=["BUYER"],
        scheduled_start="2026-07-30T13:00:00Z", defects=[("Panel", "MAJOR")])
    approved = validate_success(api.approve_report(report["id"], SCHED))
    assert approved["final_risk_score"] == 133
    assert approved["severity_band"] == "MAJOR"


# ---------------------------------------------------------------------------
# add-on uniqueness per kind
# ---------------------------------------------------------------------------
def test_duplicate_addon_kind_rejected(api):
    """PRD §3.4: "Each add-on `kind` may appear at most once per order, and the order
    must still be `REQUESTED` or `SCHEDULED` (not yet started); a duplicate kind or an
    already-started order is rejected with `ERR_DUPLICATE_ADDON`."

    Design: Corner/state_machines/corner_double_addon_same_kind_rejected
    """
    cfg, order = setup_requested_order(inspection_type="BUYER")
    validate_success(api.create_addon(order["id"], F.create_addon_payload("RADON"), SCHED), 201)
    resp = api.create_addon(order["id"], F.create_addon_payload("RADON"), SCHED)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ADDON.value)
