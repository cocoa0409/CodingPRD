"""Composite setup helpers for multi-step test prerequisites.

Every fixture builds its preconditions from scratch via PRD endpoints (the
server restarts against an empty store before each test). Setup calls use
get_success_data() so failures surface as clear "Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_carrier_payload,
    create_price_list_entry_payload,
    create_customer_payload,
    create_policy_payload,
    create_claim_payload,
    create_inspection_payload,
    create_moisture_reading_payload,
    create_photo_payload,
    create_estimate_payload,
    create_estimate_line_payload,
    create_negotiation_round_payload,
    create_append_dispositions_payload,
    create_respond_payload,
    create_supplement_payload,
    create_code_upgrade_payload,
    create_work_authorization_payload,
    create_payment_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS, make_customer_headers

ADMIN = TEST_USERS["contractor_admin_headers"]
ESTIMATOR = TEST_USERS["estimator_headers"]
TECH = TEST_USERS["field_technician_headers"]
ADJUSTER = TEST_USERS["adjuster_headers"]

# Default single-entry/single-line scenario: 200c GENERAL LABOR entry.
DEFAULT_ENTRY_SPEC = {"category_code": "GEN-1", "trade": "GENERAL", "kind": "LABOR",
                      "unit": "EA", "unit_price_cents": 200}


# ─── Tier 0: base entity builders ───────────────────────────────────

def make_carrier(**overrides) -> dict:
    return get_success_data(api_client.create_carrier(create_carrier_payload(**overrides), ADMIN))


def make_price_entry(carrier_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_price_list_entry(
        carrier_id, create_price_list_entry_payload(**overrides), ADMIN))


def make_customer(**overrides) -> dict:
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), ADMIN))


def make_policy(customer_id: str, carrier_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_policy(
        create_policy_payload(customer_id, carrier_id, **overrides), ADMIN))


def make_claim(policy_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_claim(
        create_claim_payload(policy_id, **overrides), ADMIN))


def read_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_claim(claim_id, ADMIN))


def transition_claim(claim_id: str, to: str) -> dict:
    return get_success_data(api_client.transition_claim(claim_id, {"to": to}, ADMIN))


# ─── Tier 1: claim bootstrap + state progression ────────────────────

def make_claim_ctx(*, carrier_overrides=None, entry_specs=(DEFAULT_ENTRY_SPEC,),
                   policy_overrides=None, cause_of_loss="FIRE",
                   date_of_loss="2026-03-10T00:00:00Z", policy_number="POL-1") -> dict:
    """Carrier (+ price entries) → customer → policy → claim (INTAKE)."""
    carrier = make_carrier(**(carrier_overrides or {}))
    entries = [make_price_entry(carrier["id"], **spec) for spec in entry_specs]
    customer = make_customer()
    po = dict(policy_overrides or {})
    po.setdefault("policy_number", policy_number)
    policy = make_policy(customer["id"], carrier["id"], **po)
    claim = make_claim(policy["id"], cause_of_loss=cause_of_loss,
                       date_of_loss=date_of_loss)
    return {"carrier": carrier, "entries": entries, "customer": customer,
            "policy": policy, "claim": claim}


def claim_to_assessing(ctx: dict) -> dict:
    ctx["claim"] = transition_claim(ctx["claim"]["id"], "ASSESSING")
    return ctx


def claim_to_estimating(ctx: dict) -> dict:
    if ctx["claim"]["status"] == "INTAKE":
        claim_to_assessing(ctx)
    ctx["claim"] = transition_claim(ctx["claim"]["id"], "ESTIMATING")
    return ctx


# ─── Tier 2: inspection + evidence ──────────────────────────────────

def schedule_inspection(claim_id: str, *, assignee_id="tech-1",
                        start="2026-05-02T09:00:00Z", end="2026-05-02T10:00:00Z",
                        insp_type="INITIAL") -> dict:
    return get_success_data(api_client.create_inspection(
        claim_id,
        create_inspection_payload(type=insp_type, assignee_id=assignee_id,
                                  scheduled_start=start, scheduled_end=end),
        TECH))


def add_photo(claim_id: str, *, inspection_id=None, supplement_id=None, tag="AREA",
              file_ref="photo.jpg", captured_at="2026-05-02T09:05:00Z", as_role=None) -> dict:
    payload = create_photo_payload(claim_id, tag=tag, file_ref=file_ref,
                                   captured_at=captured_at)
    if inspection_id is not None:
        payload["inspection_id"] = inspection_id
    if supplement_id is not None:
        payload["supplement_id"] = supplement_id
    return get_success_data(api_client.create_photo(payload, as_role or TECH))


def add_evidence_photos(claim_id: str, inspection_id: str, n: int = 3,
                        tags=("AREA", "AREA", "LOSS_OVERVIEW")) -> list:
    """Attach n evidence photos (default 3) to an inspection (PRD §3.3 gate)."""
    photos = []
    for i in range(n):
        tag = tags[i] if i < len(tags) else "AREA"
        photos.append(add_photo(claim_id, inspection_id=inspection_id, tag=tag,
                                file_ref=f"ev{i}.jpg",
                                captured_at=f"2026-05-02T09:0{5 + i}:00Z"))
    return photos


def add_reading(inspection_id: str, *, area="kitchen", material="drywall",
                reading_value=13, dry_standard=12,
                recorded_at="2026-05-02T09:10:00Z") -> dict:
    return get_success_data(api_client.create_moisture_reading(
        inspection_id,
        create_moisture_reading_payload(area=area, material=material,
                                        reading_value=reading_value,
                                        dry_standard=dry_standard,
                                        recorded_at=recorded_at),
        TECH))


def complete_inspection(inspection_id: str) -> dict:
    return get_success_data(api_client.complete_inspection(inspection_id, TECH))


def add_completed_inspection(ctx: dict, *, readings=None, assignee_id="tech-1",
                             start="2026-05-02T09:00:00Z", end="2026-05-02T10:00:00Z",
                             insp_type="INITIAL") -> dict:
    """Schedule + evidence + complete an inspection on ctx's claim.

    WATER/MOLD claims need at least one moisture reading to complete;
    the default reading (13 vs dry 12) is non-wet so the completion
    moisture gate passes downstream.
    """
    claim = ctx["claim"]
    insp = schedule_inspection(claim["id"], assignee_id=assignee_id,
                               start=start, end=end, insp_type=insp_type)
    add_evidence_photos(claim["id"], insp["id"])
    if readings is None:
        readings = []
        if claim["cause_of_loss"] in ("WATER", "MOLD"):
            readings = [{}]
    for r in readings:
        add_reading(insp["id"], **r)
    insp = complete_inspection(insp["id"])
    ctx["inspection"] = insp
    return ctx


def setup_estimating_claim(*, with_completed_inspection=True, readings=None,
                           **kwargs) -> dict:
    """Claim driven INTAKE → ASSESSING → ESTIMATING with (optionally) a
    COMPLETED inspection. Returns the context dict."""
    ctx = make_claim_ctx(**kwargs)
    claim_to_assessing(ctx)
    if with_completed_inspection:
        add_completed_inspection(ctx, readings=readings)
    claim_to_estimating(ctx)
    return ctx


# ─── Tier 3: estimate composition + lifecycle ───────────────────────

def make_estimate(claim_id: str) -> dict:
    """Create the claim's INITIAL estimate (reads the live claim version for OCC)."""
    claim = read_claim(claim_id)
    return get_success_data(api_client.create_estimate(
        claim_id, create_estimate_payload(claim["version"]), ESTIMATOR))


def add_line(estimate_id: str, price_list_entry_id: str, qty, **overrides) -> dict:
    return get_success_data(api_client.create_estimate_line(
        estimate_id, create_estimate_line_payload(price_list_entry_id, qty, **overrides),
        ESTIMATOR))


def read_estimate(estimate_id: str) -> dict:
    return get_success_data(api_client.get_estimate(estimate_id, ESTIMATOR))


def submit_estimate(estimate_id: str) -> dict:
    return get_success_data(api_client.submit_estimate(estimate_id, ESTIMATOR))


def approve_estimate(estimate_id: str) -> dict:
    return get_success_data(api_client.approve_estimate(estimate_id, ADJUSTER))


def build_estimate(ctx: dict, line_specs=None) -> dict:
    """DRAFT estimate on ctx's claim with lines from line_specs.

    line_specs: list of (entry_index, qty) tuples or dicts with
    {entry: <index>, qty: <n>, plus any line payload overrides}.
    """
    estimate = make_estimate(ctx["claim"]["id"])
    lines = []
    for spec in (line_specs if line_specs is not None else [(0, 1000)]):
        if isinstance(spec, dict):
            spec = dict(spec)
            entry_idx = spec.pop("entry", 0)
            qty = spec.pop("qty")
            lines.append(add_line(estimate["id"], ctx["entries"][entry_idx]["id"],
                                  qty, **spec))
        else:
            entry_idx, qty = spec
            lines.append(add_line(estimate["id"], ctx["entries"][entry_idx]["id"], qty))
    ctx["estimate"] = read_estimate(estimate["id"])
    ctx["lines"] = lines
    return ctx


def setup_draft_estimate(**kwargs) -> dict:
    """Claim in ASSESSING/ESTIMATING + DRAFT estimate with lines."""
    line_specs = kwargs.pop("line_specs", None)
    ctx = setup_estimating_claim(**kwargs)
    return build_estimate(ctx, line_specs)


def setup_submitted_estimate(**kwargs) -> dict:
    """Estimate SUBMITTED; claim moved ESTIMATING → NEGOTIATING."""
    ctx = setup_draft_estimate(**kwargs)
    ctx["estimate"] = submit_estimate(ctx["estimate"]["id"])
    ctx["claim"] = read_claim(ctx["claim"]["id"])
    return ctx


def setup_approved_claim(**kwargs) -> dict:
    """Estimate APPROVED; claim NEGOTIATING → APPROVED (aggregates recomputed)."""
    ctx = setup_submitted_estimate(**kwargs)
    ctx["estimate"] = approve_estimate(ctx["estimate"]["id"])
    ctx["claim"] = read_claim(ctx["claim"]["id"])
    return ctx


# ─── Tier 4: work authorization / payments / execution ──────────────

def make_and_sign_wa(ctx: dict, *, direct_pay=True, deductible_acknowledged=True) -> dict:
    """Create + customer-sign a work authorization on an APPROVED/ON_HOLD claim."""
    claim_id = ctx["claim"]["id"]
    wa = get_success_data(api_client.create_work_authorization(
        claim_id, create_work_authorization_payload(direct_pay, deductible_acknowledged),
        ADMIN))
    wa = get_success_data(api_client.sign_work_authorization(
        wa["id"], make_customer_headers(ctx["customer"]["id"])))
    ctx["wa"] = wa
    ctx["claim"] = read_claim(claim_id)
    return ctx


def list_claim_payments(claim_id: str) -> list:
    return get_success_data(api_client.list_payments(claim_id, ADMIN))


def drive_payment_to_cleared(payment_id: str, direction: str) -> dict:
    """REQUESTED → APPROVED → ISSUED → CLEARED honoring the direction-role split
    (carrier direction: Adjuster approves/issues; customer direction: admin)."""
    role = ADJUSTER if direction == "CARRIER_TO_CONTRACTOR" else ADMIN
    get_success_data(api_client.approve_payment(payment_id, role))
    get_success_data(api_client.issue_payment(payment_id, role))
    return get_success_data(api_client.clear_payment(payment_id, ADMIN))


def find_payment(claim_id: str, payment_type: str) -> dict:
    for p in list_claim_payments(claim_id):
        if p["type"] == payment_type:
            return p
    raise AssertionError(f"Setup step failed: no {payment_type} payment on claim {claim_id}")


def setup_in_progress_claim(*, direct_pay=True, clear_advance=True, **kwargs) -> dict:
    """Claim APPROVED → WA signed (→ AUTHORIZED) → optional ACV advance CLEARED
    → start-work → IN_PROGRESS."""
    ctx = setup_approved_claim(**kwargs)
    make_and_sign_wa(ctx, direct_pay=direct_pay)
    if direct_pay:
        advance = find_payment(ctx["claim"]["id"], "ACV_ADVANCE")
        ctx["advance"] = advance
        if clear_advance:
            ctx["advance"] = drive_payment_to_cleared(advance["id"], advance["direction"])
            ctx["claim"] = read_claim(ctx["claim"]["id"])
    ctx["claim"] = get_success_data(api_client.start_work(ctx["claim"]["id"], ADMIN))
    return ctx


def setup_complete_claim(**kwargs) -> dict:
    """Claim driven through work completion (IN_PROGRESS → COMPLETE)."""
    ctx = setup_in_progress_claim(**kwargs)
    ctx["claim"] = get_success_data(api_client.complete_work(ctx["claim"]["id"], ADMIN))
    return ctx


def setup_invoiced_claim(*, issue=True, admin_user_id="test-admin-1", **kwargs) -> dict:
    """Claim COMPLETE → invoice created (estimates LOCKED) → optionally ISSUED."""
    from .test_users import make_contractor_admin_headers
    ctx = setup_complete_claim(**kwargs)
    admin = make_contractor_admin_headers(admin_user_id)
    invoice = get_success_data(api_client.create_invoice(ctx["claim"]["id"], admin))
    ctx["invoice"] = invoice
    ctx["estimate"] = read_estimate(ctx["estimate"]["id"])
    if issue:
        ctx["invoice"] = get_success_data(api_client.issue_invoice(invoice["id"], admin))
        ctx["claim"] = read_claim(ctx["claim"]["id"])
    return ctx


# ─── Tier 5: supplements / negotiation ──────────────────────────────

def make_submitted_supplement(ctx: dict, narrative="Hidden damage found") -> dict:
    """DRAFT supplement + 2 SUPPLEMENT_EVIDENCE photos → SUBMITTED."""
    claim_id = ctx["claim"]["id"]
    supp = get_success_data(api_client.create_supplement(
        claim_id, create_supplement_payload(narrative), ESTIMATOR))
    add_photo(claim_id, supplement_id=supp["id"], tag="SUPPLEMENT_EVIDENCE",
              file_ref="s1.jpg", captured_at="2026-05-06T09:00:00Z", as_role=ESTIMATOR)
    add_photo(claim_id, supplement_id=supp["id"], tag="SUPPLEMENT_EVIDENCE",
              file_ref="s2.jpg", captured_at="2026-05-06T09:01:00Z", as_role=ESTIMATOR)
    supp = get_success_data(api_client.submit_supplement(supp["id"], ESTIMATOR))
    ctx["supplement"] = supp
    return ctx


def approve_supplement_and_get_estimate(ctx: dict) -> dict:
    """Adjuster-approve the submitted supplement; fetch the spawned SUPPLEMENT
    estimate and attach it to ctx as supplement_estimate."""
    supp = ctx["supplement"]
    get_success_data(api_client.approve_supplement(supp["id"], ADJUSTER))
    estimates = get_success_data(api_client.list_supplement_estimates(supp["id"], ESTIMATOR))
    ctx["supplement_estimate"] = estimates[0]
    ctx["claim"] = read_claim(ctx["claim"]["id"])
    return ctx


def make_countered_estimate(ctx: dict, dispositions) -> dict:
    """Adjuster counter-offer on ctx's SUBMITTED estimate; attaches round +
    its dispositions (listed in creation order)."""
    rnd = get_success_data(api_client.create_negotiation_round(
        ctx["estimate"]["id"], create_negotiation_round_payload(dispositions), ADJUSTER))
    ctx["round"] = rnd
    ctx["dispositions"] = get_success_data(
        api_client.list_dispositions(rnd["id"], ADJUSTER))
    ctx["estimate"] = read_estimate(ctx["estimate"]["id"])
    return ctx


def set_logical_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), ADMIN))
