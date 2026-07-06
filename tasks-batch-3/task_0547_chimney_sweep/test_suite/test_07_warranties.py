"""Warranties: the labor-only vs parts-inclusive claim-credit dual variant, the
repair-completed precondition, state-beats-safety precedence, and term expiry."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId, validate_success, validate_error,
)
from test_helpers import factories as F
from test_helpers import fixtures as fx

DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


def _issue_two_warranties():
    """Two COMPLETED repairs (labor 8000, parts 4000), warranties W1 LABOR_ONLY and
    W2 PARTS_INCLUSIVE (term 12), issued 2026-06-01, clock advanced to 2026-09-01
    (elapsed 3 whole months). Returns (job_id, w1, w2)."""
    fx.set_clock("2026-06-01T00:00:00Z")
    setup = fx.setup_safe_draft_job(job_overrides={"inspection_level": 1, "repair_authorization_cents": 100000})
    tech = setup["technician"]
    job_id = setup["job"]["id"]
    ro1 = fx.add_completed_repair(job_id, tech, repair_type="CAP", part_sku="CAP-STD",
                                  quoted_cost_cents=12000, final_cost_cents=12000, labor_cents=8000)
    ro2 = fx.add_completed_repair(job_id, tech, repair_type="LINER", part_sku="LNR-SS6",
                                  quoted_cost_cents=12000, final_cost_cents=12000, labor_cents=8000)
    w1 = fx.issue_warranty(job_id, ro1["id"], coverage_type="LABOR_ONLY", term_months=12)
    w2 = fx.issue_warranty(job_id, ro2["id"], coverage_type="PARTS_INCLUSIVE", term_months=12)
    fx.set_clock("2026-09-01T00:00:00Z")
    return job_id, w1, w2


# ---------------------------------------------------------------- dvc warranty credit
def test_labor_only_claim_credits_full_labor():
    """PRD §3.7: "For a `LABOR_ONLY` warranty, the credit is the full
    `covered_labor_cents`, with parts never covered and no proration."

    Design: Difficulty/dual_variant_calc/dvc_warranty_labor_only_vs_parts_inclusive
    """
    _job_id, w1, _w2 = _issue_two_warranties()
    resp = api_client.file_claim_warranty(w1["id"], {"claimed_repair_type": "CAP"}, BILLING)
    data = validate_success(resp, 200)
    assert data["last_claim_credit_cents"] == 8000


def test_parts_inclusive_claim_prorates_parts():
    """PRD §3.7: "For a `PARTS_INCLUSIVE` warranty, first determine `elapsed_months`
    as the whole calendar months from `issued_at` to the current clock instant,
    taking the floor; the remaining fraction of the term is `term_months` minus
    `elapsed_months`, all divided by `term_months`; the credit is the full
    `covered_labor_cents` plus the `covered_parts_cents` multiplied by that
    remaining fraction, with the parts portion rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/dvc_warranty_labor_only_vs_parts_inclusive
    """
    _job_id, _w1, w2 = _issue_two_warranties()
    resp = api_client.file_claim_warranty(w2["id"], {"claimed_repair_type": "LINER"}, BILLING)
    data = validate_success(resp, 200)
    # labor 8000 + round_half_up(4000 * (12-3)/12) = 8000 + 3000 = 11000
    assert data["last_claim_credit_cents"] == 11000


# ---------------------------------------------------------------- cesd warranty needs completed repair
def test_warranty_issue_rejected_while_repair_in_progress():
    """PRD §3.7: "Issuance requires that the referenced repair order is actually
    `COMPLETED`; otherwise `ERR_REPAIR_NOT_COMPLETED`."

    Design: Difficulty/cross_entity_state_dependency/cesd_warranty_issue_requires_repair_completed
    """
    setup = fx.setup_safe_draft_job(job_overrides={"inspection_level": 1, "repair_authorization_cents": 50000})
    tech = setup["technician"]
    job_id = setup["job"]["id"]
    ro = fx.propose_repair(job_id, technician=tech, repair_type="LINER", part_sku="LNR-SS6", quoted_cost_cents=20000)
    fx.approve_repair(ro["id"])
    fx.start_repair(ro["id"], tech)  # IN_PROGRESS, not COMPLETED
    resp = api_client.create_warranty(
        F.create_warranty_payload(repair_order_id=ro["id"], service_job_id=job_id,
                                  coverage_type="PARTS_INCLUSIVE", term_months=24),
        BILLING,
    )
    validate_error(resp, ApiErrorId.ERR_REPAIR_NOT_COMPLETED)


def test_warranty_issue_rejected_while_repair_approved():
    """PRD §3.7: "Issuance requires that the referenced repair order is actually
    `COMPLETED`; otherwise `ERR_REPAIR_NOT_COMPLETED`."

    Design: Difficulty/cross_entity_state_dependency/cesd_warranty_issue_requires_repair_completed
    """
    setup = fx.setup_safe_draft_job(job_overrides={"inspection_level": 1, "repair_authorization_cents": 50000})
    tech = setup["technician"]
    job_id = setup["job"]["id"]
    ro = fx.propose_repair(job_id, technician=tech, repair_type="CAP", part_sku="CAP-STD", quoted_cost_cents=9000)
    fx.approve_repair(ro["id"])  # APPROVED, not COMPLETED
    resp = api_client.create_warranty(
        F.create_warranty_payload(repair_order_id=ro["id"], service_job_id=job_id,
                                  coverage_type="LABOR_ONLY", term_months=12),
        BILLING,
    )
    validate_error(resp, ApiErrorId.ERR_REPAIR_NOT_COMPLETED)


# ---------------------------------------------------------------- ppvc state beats safety
def test_state_check_wins_over_safety_on_unsafe_job():
    """PRD §2.11: "7. **State validity** — the target is in a legal state for the
    operation, else the appropriate 409 (`ERR_INVALID_STATE_TRANSITION`,
    `ERR_JOB_NOT_IN_PROGRESS`, `ERR_JOB_HAS_OPEN_REPAIRS`, `ERR_JOB_TERMINAL`,
    `ERR_REPAIR_NOT_COMPLETED`, `ERR_WARRANTY_NOT_CLAIMABLE`, or
    `ERR_REMINDER_NOT_DUE`)."
    PRD §2.11: "9. **Safety posture** — posture is `SAFE` or `CONDITIONS` where
    required, else `ERR_JOB_UNSAFE` (403)."
    PRD §2.11: "A check earlier in this list always takes precedence over one later
    in the list when both would fail."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_state_beats_safety_on_warranty_issue
    """
    setup = fx.setup_job(job_overrides={"inspection_level": 2, "repair_authorization_cents": 100000})
    tech = setup["technician"]
    job_id = setup["job"]["id"]
    ro = fx.propose_repair(job_id, technician=tech, repair_type="CAP", part_sku="CAP-STD", quoted_cost_cents=9000)
    fx.approve_repair(ro["id"])  # APPROVED (not COMPLETED)
    fx.record_safety_check(job_id, tech, co_ppm=12, draft_ok=False)  # -> UNSAFE
    resp = api_client.create_warranty(
        F.create_warranty_payload(repair_order_id=ro["id"], service_job_id=job_id,
                                  coverage_type="LABOR_ONLY", term_months=12),
        BILLING,
    )
    validate_error(resp, ApiErrorId.ERR_REPAIR_NOT_COMPLETED)


def test_state_check_wins_over_safety_on_condemned_job():
    """PRD §2.11: "7. **State validity** — the target is in a legal state for the
    operation, else the appropriate 409 (`ERR_INVALID_STATE_TRANSITION`,
    `ERR_JOB_NOT_IN_PROGRESS`, `ERR_JOB_HAS_OPEN_REPAIRS`, `ERR_JOB_TERMINAL`,
    `ERR_REPAIR_NOT_COMPLETED`, `ERR_WARRANTY_NOT_CLAIMABLE`, or
    `ERR_REMINDER_NOT_DUE`)."
    PRD §2.11: "9. **Safety posture** — posture is `SAFE` or `CONDITIONS` where
    required, else `ERR_JOB_UNSAFE` (403)."
    PRD §2.11: "A check earlier in this list always takes precedence over one later
    in the list when both would fail."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_state_beats_safety_on_warranty_issue
    """
    setup = fx.setup_job(job_overrides={"inspection_level": 2, "repair_authorization_cents": 100000})
    tech = setup["technician"]
    job_id = setup["job"]["id"]
    ro = fx.propose_repair(job_id, technician=tech, repair_type="CAP", part_sku="CAP-STD", quoted_cost_cents=9000)
    fx.approve_repair(ro["id"])  # APPROVED (not COMPLETED)
    fx.record_safety_check(job_id, tech, co_ppm=70, draft_ok=True)  # -> CONDEMNED
    resp = api_client.create_warranty(
        F.create_warranty_payload(repair_order_id=ro["id"], service_job_id=job_id,
                                  coverage_type="LABOR_ONLY", term_months=12),
        BILLING,
    )
    validate_error(resp, ApiErrorId.ERR_REPAIR_NOT_COMPLETED)


# ---------------------------------------------------------------- corner: warranty expired
def test_warranty_claim_after_term_expired():
    """PRD §3.7: "The claim must also be within term: the logical clock must be no
    later than `issued_at` advanced by `term_months` whole months, else
    `ERR_WARRANTY_EXPIRED`."

    Design: Corner/validations/error_warranty_expired_on_file_claim
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    setup = fx.setup_safe_draft_job(job_overrides={"inspection_level": 1, "repair_authorization_cents": 100000})
    tech = setup["technician"]
    job_id = setup["job"]["id"]
    ro = fx.add_completed_repair(job_id, tech, repair_type="CAP", part_sku="CAP-STD",
                                 quoted_cost_cents=12000, final_cost_cents=12000, labor_cents=8000)
    warranty = fx.issue_warranty(job_id, ro["id"], coverage_type="PARTS_INCLUSIVE", term_months=1)
    fx.set_clock("2026-08-01T00:00:00Z")  # 2 months elapsed, term was 1 month
    resp = api_client.file_claim_warranty(warranty["id"], {"claimed_repair_type": "CAP"}, BILLING)
    validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED)
