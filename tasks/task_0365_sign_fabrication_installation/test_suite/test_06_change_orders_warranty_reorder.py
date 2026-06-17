"""Change-order apply cascade & ledger, cancel-cascade, warranty coverage
boundaries & adjudication, reorder cloning, project close, and OCC on apply.

Covers transitive_cascade, compensating_invariant, boundary_precision (warranty),
the OCC-apply and reorder cross-cutting instances, and corner error/close cases.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    assert_contract_ledger_invariant,
    create_project, create_sent_estimate, create_permitting_project,
    create_fabrication_project, create_installed_project, create_closed_project,
    create_passed_survey, register_crew, register_equipment, schedule_install_job,
    create_change_order_payload, create_install_job_payload, create_reorder_payload,
    set_clock, get_project_version,
    TEST_USERS,
)

SM = TEST_USERS["shop_manager_headers"]
CUST = TEST_USERS["customer_headers"]


def _fabrication_with_in_production_wo(name, addr):
    """FABRICATION project whose RELEASED work order is started to IN_PRODUCTION."""
    project, estimate, survey, wo = create_fabrication_project(
        customer_name=name, site_address=addr,
        sign_type="WALL", face_width_in=36, face_height_in=24, placement_height_ft=6)
    api_client.start_work_order(project["id"], wo["id"], SM)
    return project, estimate, wo


# ═══ Queue A: transitive_cascade / change_order_apply_three_hop_cascade ════════

def test_change_order_apply_three_hop_cascade(api):
    """PRD §3.6: "the project's contract_total_cents has this change order's
    delta_total_cents added to it as a compensating ledger sync; and if a
    fabrication work order exists in IN_PRODUCTION or QC_HOLD, that work order is
    cancelled and a new RELEASED work order is created in its place, with the
    project's phase reset back to FABRICATION if it had already advanced."

    Design: Difficulty/transitive_cascade/change_order_apply_three_hop_cascade
    """
    project, estimate, wo1 = _fabrication_with_in_production_wo("Casc Co", "4 Chain St")
    co = get_success_data(api.create_change_order(
        project["id"], create_change_order_payload(reason="wider", new_face_width_in=60), SM))
    api.approve_change_order(project["id"], co["id"], CUST)
    pv = get_project_version(project["id"])
    applied = validate_success(api.apply_change_order(
        project["id"], co["id"], {"expected_sign_project_version": pv}, SM), 200)
    assert applied["status"] == "APPLIED"

    project_after = validate_success(api.get_sign_project(project["id"], SM), 200)
    assert project_after["contract_total_cents"] == 31500
    assert project_after["phase"] == "FABRICATION"
    wo1_after = validate_success(api.get_work_order_by_id(wo1["id"], SM), 200)
    assert wo1_after["status"] == "CANCELLED"


def test_change_order_apply_creates_new_released_work_order(api):
    """PRD §3.6: "that work order is cancelled and a new RELEASED work order is
    created in its place."

    Design: Difficulty/transitive_cascade/change_order_apply_three_hop_cascade
    """
    project, estimate, wo1 = _fabrication_with_in_production_wo("Casc2 Co", "4 Chain St")
    co = get_success_data(api.create_change_order(
        project["id"], create_change_order_payload(reason="wider", new_face_width_in=60), SM))
    api.approve_change_order(project["id"], co["id"], CUST)
    pv = get_project_version(project["id"])
    api.apply_change_order(project["id"], co["id"], {"expected_sign_project_version": pv}, SM)

    wos = validate_success(api.list_work_orders(project["id"], SM), 200)
    released = [w for w in wos if w["status"] == "RELEASED"]
    assert len(released) >= 1, "a new RELEASED work order must exist after apply"


# ═══ Queue A: transitive_cascade / project_cancel_two_hop_supersede_cascade ════

def test_project_cancel_supersedes_sent_estimate(api):
    """PRD §3.7: "cancellation also supersedes every non-terminal art proof (those
    in DRAFT or SUBMITTED) and every non-terminal estimate (those in DRAFT or
    SENT) to SUPERSEDED."

    Design: Difficulty/transitive_cascade/project_cancel_two_hop_supersede_cascade
    """
    project, proof, estimate = create_sent_estimate(
        customer_name="Cancel Co", site_address="6 Stop St")
    cancelled = validate_success(api.cancel_sign_project(project["id"], SM), 200)
    assert cancelled["phase"] == "CANCELLED"
    est_after = validate_success(api.get_estimate_by_id(estimate["id"], SM), 200)
    assert est_after["status"] == "SUPERSEDED"


def test_project_cancel_sets_phase_cancelled(api):
    """PRD §3.7: "A project may also be cancelled by a ShopManager while it is
    still in DESIGN, ESTIMATING, or PERMITTING, driving its phase to CANCELLED."

    Design: Difficulty/transitive_cascade/project_cancel_two_hop_supersede_cascade
    """
    project, proof, estimate = create_sent_estimate(
        customer_name="Cancel2 Co", site_address="6 Stop St")
    cancelled = validate_success(api.cancel_sign_project(project["id"], SM), 200)
    assert cancelled["phase"] == "CANCELLED"


# ═══ Queue A: compensating_invariant / change_order_apply_contract_ledger ═════

def test_contract_ledger_equals_baseline_plus_applied_delta(api):
    """PRD §3.2: "contract_total_cents equals the accepted estimate's total_cents
    plus the sum of delta_total_cents across only those change orders in APPLIED
    status."

    Design: Difficulty/compensating_invariant/change_order_apply_contract_ledger_invariant
    """
    project, estimate, survey, wo = create_fabrication_project(
        customer_name="Led Co", site_address="50 Money St",
        sign_type="WALL", face_width_in=36, face_height_in=24, placement_height_ft=6)
    co = get_success_data(api.create_change_order(
        project["id"], create_change_order_payload(reason="wider", new_face_width_in=60), SM))
    assert co["delta_total_cents"] == 7200
    api.approve_change_order(project["id"], co["id"], CUST)
    pv = get_project_version(project["id"])
    api.apply_change_order(project["id"], co["id"], {"expected_sign_project_version": pv}, SM)
    project_after = validate_success(api.get_sign_project(project["id"], SM), 200)
    assert project_after["contract_total_cents"] == 31500


def test_contract_ledger_invariant_holds_via_helper(api):
    """PRD §3.2: "Because each delta is already a whole-cent integer, the running
    sum requires no further rounding."

    Design: Difficulty/compensating_invariant/change_order_apply_contract_ledger_invariant
    """
    project, estimate, survey, wo = create_fabrication_project(
        customer_name="Led2 Co", site_address="50 Money St",
        sign_type="WALL", face_width_in=36, face_height_in=24, placement_height_ft=6)
    baseline = estimate["total_cents"]
    co = get_success_data(api.create_change_order(
        project["id"], create_change_order_payload(reason="wider", new_face_width_in=60), SM))
    api.approve_change_order(project["id"], co["id"], CUST)
    pv = get_project_version(project["id"])
    api.apply_change_order(project["id"], co["id"], {"expected_sign_project_version": pv}, SM)
    project_after = validate_success(api.get_sign_project(project["id"], SM), 200)
    assert_contract_ledger_invariant(project_after, baseline, [co["delta_total_cents"]])


# ═══ Queue A: compensating_invariant / install_fail_then_cancel_booking ═══════

def test_failed_install_releases_equipment_for_rebooking(api):
    """PRD §3.5: "A dispatched job that goes wrong can be failed, moving it
    DISPATCHED → FAILED and releasing the crew and equipment bookings for the
    window; failure is not terminal, so a fresh install job may be scheduled to
    retry."

    Design: Difficulty/compensating_invariant/install_fail_then_cancel_booking_count_invariant
    """
    project, estimate, survey, wo = create_fabrication_project(
        placement_height_ft=25, customer_name="Rel Co", site_address="60 Free Rd")
    api.start_work_order(project["id"], wo["id"], SM)
    api.qc_hold_work_order(project["id"], wo["id"], SM)
    api.qc_decide_work_order(project["id"], wo["id"], {"qc_pass": True}, SM)
    crew = register_crew(name="Crew R", certified_aerial=True)
    equip = register_equipment(asset_tag="BT-R", equipment_class="BUCKET_TRUCK", max_reach_ft=40)
    job1 = get_success_data(api.create_install_job(
        project["id"], create_install_job_payload(
            wo["id"], crew["id"], "2026-06-09T09:00:00Z", "2026-06-09T10:00:00Z",
            equipment_id=equip["id"]), SM))
    api.dispatch_install_job(project["id"], job1["id"], SM)
    failed = validate_success(api.fail_install_job(project["id"], job1["id"], SM), 200)
    assert failed["status"] == "FAILED"

    # The same equipment+window must now re-book successfully (count returned to zero).
    job2 = validate_success(api.create_install_job(
        project["id"], create_install_job_payload(
            wo["id"], crew["id"], "2026-06-09T09:00:00Z", "2026-06-09T10:00:00Z",
            equipment_id=equip["id"]), SM), 201)
    assert job2["status"] == "SCHEDULED"


def test_failed_install_job_remains_failed_after_rebooking(api):
    """PRD §3.5: "A dispatched job that goes wrong can be failed, moving it
    DISPATCHED → FAILED and releasing the crew and equipment bookings for the
    window."

    Design: Difficulty/compensating_invariant/install_fail_then_cancel_booking_count_invariant
    """
    project, estimate, survey, wo = create_fabrication_project(
        placement_height_ft=25, customer_name="Rel2 Co", site_address="60 Free Rd")
    api.start_work_order(project["id"], wo["id"], SM)
    api.qc_hold_work_order(project["id"], wo["id"], SM)
    api.qc_decide_work_order(project["id"], wo["id"], {"qc_pass": True}, SM)
    crew = register_crew(name="Crew R2", certified_aerial=True)
    equip = register_equipment(asset_tag="BT-R2", equipment_class="BUCKET_TRUCK", max_reach_ft=40)
    job1 = get_success_data(api.create_install_job(
        project["id"], create_install_job_payload(
            wo["id"], crew["id"], "2026-06-09T09:00:00Z", "2026-06-09T10:00:00Z",
            equipment_id=equip["id"]), SM))
    api.dispatch_install_job(project["id"], job1["id"], SM)
    api.fail_install_job(project["id"], job1["id"], SM)
    api.create_install_job(project["id"], create_install_job_payload(
        wo["id"], crew["id"], "2026-06-09T09:00:00Z", "2026-06-09T10:00:00Z",
        equipment_id=equip["id"]), SM)
    job1_after = validate_success(api.get_install_job_by_id(job1["id"], SM), 200)
    assert job1_after["status"] == "FAILED"


# ═══ Queue A: boundary_precision_check / warranty_coverage_strict_boundary ═════

def test_warranty_cosmetic_exactly_at_boundary_not_covered(api):
    """PRD §3.7: "The claim is covered when reported_iso falls strictly before the
    install date plus the coverage-window days; the boundary is exclusive, so a
    report exactly at the install date plus the window length is not covered."

    Design: Difficulty/boundary_precision_check/warranty_coverage_strict_boundary_cosmetic
    """
    set_clock("2026-06-01T10:00:00Z")
    project, wo, crew, equip, job = create_installed_project(
        placement_height_ft=12, equipment_class="LADDER", equipment_reach=16,
        certified_aerial=False, window_start_iso="2026-06-01T08:00:00Z",
        window_end_iso="2026-06-01T09:00:00Z",
        customer_name="Edge Co", site_address="11 Edge St")
    # install 2026-06-01T10:00:00Z + 90 days = 2026-08-30T10:00:00Z (exclusive).
    claim = validate_success(api.create_warranty_claim(
        project["id"],
        {"install_job_id": job["id"], "defect_kind": "COSMETIC",
         "reported_iso": "2026-08-30T10:00:00Z"}, CUST), 201)
    assert claim["covered"] is False


def test_warranty_cosmetic_one_second_before_boundary_covered(api):
    """PRD §3.7: "The claim is covered when reported_iso falls strictly before the
    install date plus the coverage-window days."

    Design: Difficulty/boundary_precision_check/warranty_coverage_strict_boundary_cosmetic
    """
    set_clock("2026-06-01T10:00:00Z")
    project, wo, crew, equip, job = create_installed_project(
        placement_height_ft=12, equipment_class="LADDER", equipment_reach=16,
        certified_aerial=False, window_start_iso="2026-06-01T08:00:00Z",
        window_end_iso="2026-06-01T09:00:00Z",
        customer_name="Edge2 Co", site_address="11 Edge St")
    claim = validate_success(api.create_warranty_claim(
        project["id"],
        {"install_job_id": job["id"], "defect_kind": "COSMETIC",
         "reported_iso": "2026-08-30T09:59:59Z"}, CUST), 201)
    assert claim["covered"] is True


# ═══ Queue B: cross_cutting / occ_stale_version_apply_change_order ════════════

def test_occ_stale_version_apply_change_order_rejected(api):
    """PRD §2.7: "when a ShopManager applies an approved change order, the request
    must carry expected_sign_project_version equal to the project's current
    version; if a prior change order has already applied and advanced the version,
    the apply is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_apply_change_order_rejected
    """
    project, estimate, survey, wo = create_fabrication_project(
        customer_name="Occ Co", site_address="33 Ver St",
        sign_type="WALL", face_width_in=36, face_height_in=24, placement_height_ft=6)
    co = get_success_data(api.create_change_order(
        project["id"], create_change_order_payload(reason="wider", new_face_width_in=60), SM))
    api.approve_change_order(project["id"], co["id"], CUST)
    current = get_project_version(project["id"])
    res = api.apply_change_order(
        project["id"], co["id"], {"expected_sign_project_version": current - 1}, SM)
    validate_error(res, "ERR_STALE_VERSION")


# ═══ Queue B: cross_cutting / reorder_confirm_clones_closed_project ═══════════

def test_reorder_confirm_clones_closed_project_carrying_contract(api):
    """PRD §3.8: "Confirmation drives the reorder REQUESTED → CONFIRMED and clones
    a brand-new sign project in DESIGN... and records the clone's id in the
    reorder's reorder_project_id. The reprice flag governs the money: ... when it
    is false, the cloned project carries the source's contract_total_cents forward
    unchanged."

    Design: Corner/cross_cutting_complexity_layers/reorder_confirm_clones_closed_project_with_repriced_flag
    """
    project = create_closed_project(
        install_iso="2026-06-01T10:00:00Z", placement_height_ft=12,
        equipment_class="LADDER", equipment_reach=16, certified_aerial=False,
        customer_name="Clone Co", site_address="34 Copy St")
    assert project["contract_total_cents"] == 24300
    reorder = get_success_data(api.create_reorder(
        project["id"], create_reorder_payload(quantity=1, reprice=False), SM))
    confirmed = validate_success(api.confirm_reorder(project["id"], reorder["id"], SM), 200)
    assert confirmed["status"] == "CONFIRMED"
    new_project = validate_success(
        api.get_sign_project(confirmed["reorder_project_id"], SM), 200)
    assert new_project["phase"] == "DESIGN"
    assert new_project["contract_total_cents"] == 24300


# ═══ Queue B: corner errors / state_machines (close, warranty, reorder) ══════

def test_reorder_confirm_source_not_closed_rejected(api):
    """PRD §3.8: "A ShopManager confirms a REQUESTED reorder, but only when the
    source project is CLOSED; confirming against a source that is not closed is
    rejected with ERR_SOURCE_NOT_CLOSED."

    Design: Corner/errors/error_source_not_closed_on_reorder_confirm
    """
    project = create_project(customer_name="Reo Co", site_address="28 Again St")
    reorder = get_success_data(api.create_reorder(
        project["id"], create_reorder_payload(quantity=2, reprice=True), SM))
    res = api.confirm_reorder(project["id"], reorder["id"], SM)
    validate_error(res, "ERR_SOURCE_NOT_CLOSED")


def test_approve_uncovered_warranty_claim_out_of_warranty(api):
    """PRD §3.7: "an approval drives the claim OPEN → APPROVED, but only if the
    claim is covered — approving an uncovered claim is rejected with
    ERR_OUT_OF_WARRANTY."

    Design: Corner/errors/error_out_of_warranty_on_claim_approve
    """
    set_clock("2026-06-01T10:00:00Z")
    project, wo, crew, equip, job = create_installed_project(
        placement_height_ft=12, equipment_class="LADDER", equipment_reach=16,
        certified_aerial=False, window_start_iso="2026-06-01T08:00:00Z",
        window_end_iso="2026-06-01T09:00:00Z",
        customer_name="OOW Co", site_address="29 Late St")
    claim = get_success_data(api.create_warranty_claim(
        project["id"],
        {"install_job_id": job["id"], "defect_kind": "COSMETIC",
         "reported_iso": "2026-10-01T10:00:00Z"}, CUST))
    assert claim["covered"] is False
    res = api.decide_warranty_claim(project["id"], claim["id"], {"decision": "APPROVE"}, SM)
    validate_error(res, "ERR_OUT_OF_WARRANTY")


def test_close_project_with_open_claim_rejected(api):
    """PRD §3.7: "A ShopManager closes a project from WARRANTY, driving its phase
    to CLOSED, but only when no warranty claim of the project still sits in OPEN
    or APPROVED; an attempt to close with such a claim outstanding is rejected
    with ERR_OPEN_CLAIM."

    Design: Corner/validations/close_project_with_open_claim_rejected
    """
    set_clock("2026-06-01T10:00:00Z")
    project, wo, crew, equip, job = create_installed_project(
        placement_height_ft=12, equipment_class="LADDER", equipment_reach=16,
        certified_aerial=False, window_start_iso="2026-06-01T08:00:00Z",
        window_end_iso="2026-06-01T09:00:00Z",
        customer_name="Open Co", site_address="26 Claim St")
    get_success_data(api.create_warranty_claim(
        project["id"],
        {"install_job_id": job["id"], "defect_kind": "COSMETIC",
         "reported_iso": "2026-06-10T10:00:00Z"}, CUST))
    res = api.close_sign_project(project["id"], SM)
    validate_error(res, "ERR_OPEN_CLAIM")
