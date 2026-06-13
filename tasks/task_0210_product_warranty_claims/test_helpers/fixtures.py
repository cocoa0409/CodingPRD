"""Composite setup helpers for the Product Warranty Claims benchmark (PRD §3).

Every helper builds its preconditions from scratch through PRD-declared endpoints.
The runner restarts the API server before every individual pytest test, so each
test starts from an empty database — no entities, no clock state. These helpers
use `get_success_data()` (lenient validator) so a setup failure surfaces as a
clear "Setup failed" trace rather than a cryptic assertion deep inside a test.

Identity threading (PRD §2.1): Owner is entity_backed. After creating an Owner,
every ownership-gated call (register, proof submit, extension, claim file/withdraw,
transfer initiate/accept/reject, extension cancel) uses
`make_owner_headers(owner["id"])` — never the shared TEST_USERS constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    adjudicate_approve_payload,
    adjudicate_deny_payload,
    clock_payload,
    create_claim_payload,
    create_coverage_tier_payload,
    create_extended_warranty_payload,
    create_owner_payload,
    create_product_payload,
    create_proof_payload,
    create_registration_payload,
    transfer_payload,
)
from .test_users import (
    make_claims_processor_headers,
    make_owner_headers,
    make_warranty_admin_headers,
)


# Per-process sequence allocator for unique serials/emails/model numbers. The
# server is restarted before each test, so the counter resets per test process.
class _SeqAllocator:
    def __init__(self) -> None:
        self.n = 0

    def next(self) -> int:
        self.n += 1
        return self.n


_SEQ = _SeqAllocator()

ADMIN = make_warranty_admin_headers()
CP = make_claims_processor_headers()


def _uniq(prefix: str) -> str:
    return f"{prefix}-{_SEQ.next()}"


# ─── Tier 0: clock control (PRD §3.13) ───────────────────────────────────────
def set_clock(iso8601: str) -> None:
    """POST /_clock/set_current_utc as WarrantyAdmin (PRD §3.13)."""
    get_success_data(api_client.set_clock(clock_payload(iso8601), ADMIN))


def advance_clock(iso8601: str) -> None:
    """POST /_clock/advance (runs the expiry sweep) as WarrantyAdmin (PRD §3.13)."""
    get_success_data(api_client.advance_clock(clock_payload(iso8601), ADMIN))


# ─── Tier 1: catalogue + identity primitives (PRD §3.1, §3.2) ────────────────
def create_product(**overrides) -> dict:
    payload = create_product_payload(model_number=_uniq("MDL"), **overrides)
    return get_success_data(api_client.create_product(payload, ADMIN))


def create_tier(product_id: str, **overrides) -> dict:
    payload = create_coverage_tier_payload(product_id=product_id, **overrides)
    return get_success_data(api_client.create_coverage_tier(payload, ADMIN))


def create_owner(**overrides) -> dict:
    payload = create_owner_payload(email=f"{_uniq('owner')}@x.com", **overrides)
    return get_success_data(api_client.create_owner(payload, ADMIN))


def create_registration(product_id: str, owner_id: str, **overrides) -> dict:
    payload = create_registration_payload(
        product_id=product_id,
        owner_user_id=owner_id,
        serial_number=overrides.pop("serial_number", _uniq("SN")),
        **overrides,
    )
    return get_success_data(
        api_client.create_registration(payload, make_owner_headers(owner_id))
    )


def get_registration(reg_id: str, owner_id: str = None) -> dict:
    headers = make_owner_headers(owner_id) if owner_id else ADMIN
    return get_success_data(api_client.get_registration(reg_id, headers))


def get_registration_version(reg_id: str, owner_id: str = None) -> int:
    return get_registration(reg_id, owner_id)["version"]


# ─── Tier 2: proof + activation (PRD §3.3) ───────────────────────────────────
def submit_proof(reg_id: str, owner_id: str, **overrides) -> dict:
    payload = create_proof_payload(registration_id=reg_id, **overrides)
    return get_success_data(
        api_client.create_proof(payload, make_owner_headers(owner_id))
    )


def validate_proof(proof_id: str) -> dict:
    return get_success_data(api_client.validate_proof(proof_id, ADMIN))


def submit_and_validate_proof(reg_id: str, owner_id: str, **overrides) -> dict:
    """Submit a matching proof and validate it (PRD §3.3). Drives a REGISTERED
    registration to ACTIVE via the bubble-up side effect."""
    proof = submit_proof(reg_id, owner_id, **overrides)
    return validate_proof(proof["id"])


# ─── Tier 2.5: extensions (PRD §3.4) ─────────────────────────────────────────
def purchase_extension(reg_id: str, owner_id: str, tier_id: str, amount_paid_cents: int) -> dict:
    payload = create_extended_warranty_payload(
        registration_id=reg_id, coverage_tier_id=tier_id, amount_paid_cents=amount_paid_cents
    )
    return get_success_data(
        api_client.create_extended_warranty(payload, make_owner_headers(owner_id))
    )


def cancel_extension(ew_id: str, owner_id: str) -> dict:
    return get_success_data(
        api_client.cancel_extended_warranty(ew_id, make_owner_headers(owner_id))
    )


# ─── Tier 3: composite "active validated registration" (PRD §3.2–§3.4) ───────
def setup_active_registration(
    product_overrides=None,
    base_cap_cents=20000,
    base_depreciation="STRAIGHT_LINE",
    base_refund_eligible=None,
    purchase_price_cents=50000,
    purchase_date="2024-01-15T00:00:00Z",
    clock="2024-01-15T00:00:00Z",
):
    """Clock set; product + BASE tier created; owner created; registration created,
    proof submitted+validated -> registration ACTIVE & VALIDATED.

    Returns dict: product, base_tier, owner, registration (post-activation GET).
    """
    if clock is not None:
        set_clock(clock)
    product = create_product(**(product_overrides or {}))
    base_tier = create_tier(
        product["id"],
        tier_name="BASE",
        extension_months=0,
        price_cents=0,
        coverage_cap_cents=base_cap_cents,
        depreciation_method=base_depreciation,
        refund_eligible=base_refund_eligible,
    )
    owner = create_owner()
    reg = create_registration(
        product["id"], owner["id"],
        purchase_price_cents=purchase_price_cents,
        purchase_date=purchase_date,
    )
    submit_and_validate_proof(
        reg["id"], owner["id"],
        stated_purchase_date=purchase_date,
        stated_amount_cents=purchase_price_cents,
    )
    reg = get_registration(reg["id"], owner["id"])
    return {
        "product": product,
        "base_tier": base_tier,
        "owner": owner,
        "registration": reg,
    }


def setup_active_registration_with_extension(
    product_overrides=None,
    base_cap_cents=20000,
    ext_tier_name="GOLD",
    ext_months=24,
    ext_price_cents=12000,
    ext_cap_cents=40000,
    ext_depreciation="STRAIGHT_LINE",
    ext_refund_eligible=True,
    ext_premium_refund_method=None,
    purchase_price_cents=50000,
    purchase_date="2024-01-15T00:00:00Z",
    clock="2024-01-15T00:00:00Z",
):
    """Active validated registration plus one purchased extension tier in force.

    Returns dict: product, base_tier, ext_tier, owner, registration, extension.
    """
    base = setup_active_registration(
        product_overrides=product_overrides,
        base_cap_cents=base_cap_cents,
        purchase_price_cents=purchase_price_cents,
        purchase_date=purchase_date,
        clock=clock,
    )
    ext_tier = create_tier(
        base["product"]["id"],
        tier_name=ext_tier_name,
        extension_months=ext_months,
        price_cents=ext_price_cents,
        coverage_cap_cents=ext_cap_cents,
        depreciation_method=ext_depreciation,
        refund_eligible=ext_refund_eligible,
        premium_refund_method=ext_premium_refund_method,
    )
    extension = purchase_extension(
        base["registration"]["id"], base["owner"]["id"], ext_tier["id"], ext_price_cents
    )
    reg = get_registration(base["registration"]["id"], base["owner"]["id"])
    return {
        "product": base["product"],
        "base_tier": base["base_tier"],
        "ext_tier": ext_tier,
        "owner": base["owner"],
        "registration": reg,
        "extension": extension,
    }


# ─── Tier 4: claim lifecycle shortcuts (PRD §3.5–§3.10) ──────────────────────
def file_claim(reg_id: str, owner_id: str, **overrides) -> dict:
    payload = create_claim_payload(registration_id=reg_id, **overrides)
    return get_success_data(
        api_client.create_claim(payload, make_owner_headers(owner_id))
    )


def issue_rma(claim_id: str, processor_id: str = None) -> dict:
    headers = make_claims_processor_headers(processor_id) if processor_id else CP
    return get_success_data(api_client.issue_rma(claim_id, headers))


def adjudicate_approve(claim_id: str, resolution_type: str, repair_cost_cents=None, replace_cost_cents=None) -> dict:
    payload = adjudicate_approve_payload(
        resolution_type=resolution_type,
        repair_cost_cents=repair_cost_cents,
        replace_cost_cents=replace_cost_cents,
    )
    return get_success_data(api_client.adjudicate_claim(claim_id, payload, ADMIN))


def adjudicate_deny(claim_id: str) -> dict:
    return get_success_data(
        api_client.adjudicate_claim(claim_id, adjudicate_deny_payload(), ADMIN)
    )


def fulfill_claim(claim_id: str, processor_id: str = None) -> dict:
    headers = make_claims_processor_headers(processor_id) if processor_id else CP
    return get_success_data(api_client.fulfill_claim(claim_id, headers))


def setup_claim_in_rma(
    reg_setup_kwargs=None,
    defect_category="MANUFACTURING",
    reported_date="2024-02-15T00:00:00Z",
    with_extension=False,
    ext_kwargs=None,
):
    """Active validated registration + one claim driven to RMA_ISSUED.

    Returns the base setup dict (from setup_active_registration[_with_extension])
    augmented with a `claim` key holding the RMA_ISSUED claim.
    """
    if with_extension:
        base = setup_active_registration_with_extension(**(ext_kwargs or {}))
    else:
        base = setup_active_registration(**(reg_setup_kwargs or {}))
    claim = file_claim(
        base["registration"]["id"], base["owner"]["id"],
        defect_category=defect_category, reported_date=reported_date,
    )
    issue_rma(claim["id"])
    base["claim"] = claim
    return base


def setup_adjudicated_refund_claim(
    ext_kwargs=None,
    reported_date="2025-01-15T00:00:00Z",
    adjudicate_clock="2025-01-15T00:00:00Z",
):
    """Active validated registration WITH a refund-eligible extension, a
    MANUFACTURING claim driven through RMA_ISSUED -> ADJUDICATED with a REFUND
    resolution (PRD §3.7, §3.8). Returns base dict + `claim` (post-adjudication).
    """
    base = setup_active_registration_with_extension(**(ext_kwargs or {}))
    claim = file_claim(
        base["registration"]["id"], base["owner"]["id"],
        defect_category="MANUFACTURING", reported_date=reported_date,
    )
    issue_rma(claim["id"])
    if adjudicate_clock is not None:
        set_clock(adjudicate_clock)
    base["claim"] = adjudicate_approve(claim["id"], "REFUND")
    return base


# ─── Tier 5: transfer lifecycle (PRD §3.11) ──────────────────────────────────
def initiate_transfer(reg_id: str, owner_id: str, to_owner_id: str, expected_version: int) -> dict:
    payload = transfer_payload(
        to_owner_user_id=to_owner_id, expected_registration_version=expected_version
    )
    return get_success_data(
        api_client.transfer_registration(reg_id, payload, make_owner_headers(owner_id))
    )


def setup_pending_transfer(
    base_cap_cents=20000,
    product_overrides=None,
    transfer_clock=None,
):
    """Active validated registration owned by O1, second owner O2 created, transfer
    initiated O1 -> O2 (registration now TRANSFER_PENDING). The expected version is
    read fresh immediately before initiation so the OCC check passes.

    Returns dict: product, base_tier, owner (O1), recipient (O2), registration
    (TRANSFER_PENDING), transfer.
    """
    base = setup_active_registration(
        product_overrides=product_overrides, base_cap_cents=base_cap_cents
    )
    recipient = create_owner()
    if transfer_clock is not None:
        set_clock(transfer_clock)
    version = get_registration_version(base["registration"]["id"], base["owner"]["id"])
    transfer = initiate_transfer(
        base["registration"]["id"], base["owner"]["id"], recipient["id"], version
    )
    reg = get_registration(base["registration"]["id"], base["owner"]["id"])
    return {
        "product": base["product"],
        "base_tier": base["base_tier"],
        "owner": base["owner"],
        "recipient": recipient,
        "registration": reg,
        "transfer": transfer,
    }


def list_ledger(reg_id: str, owner_id: str = None) -> list:
    headers = make_owner_headers(owner_id) if owner_id else ADMIN
    res = api_client.list_registration_ledger(reg_id, headers)
    data = get_success_data(res)
    return data if isinstance(data, list) else data.get("items", data)
