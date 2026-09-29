"""Composite setup helpers.

Two layers live here:

* thin per-endpoint wrappers that return the created record's `data` payload, so a
  test never has to unwrap an envelope during setup;
* multi-step scene builders that walk a wholesaler from registration through
  filing, certification, posting, invoicing and auditing.

Every setup call goes through the lenient `get_success_data()` validator so a
broken precondition surfaces as a clear setup failure rather than a confusing
assertion further down. Identity is threaded explicitly: after a `LicenseeUser`
is created, every ownership-gated call in the scene uses headers built from that
user's real `id`.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as _f
from .api_client import api_client
from .constants import TEST_DEFAULTS
from .test_users import (
    TEST_USERS,
    make_certifying_officer_headers,
    make_filing_agent_headers,
)


# --------------------------------------------------------------------------
# Regulator headers used by every ComplianceOfficer-only setup call
# --------------------------------------------------------------------------

def regulator_headers() -> Dict[str, str]:
    """Headers for the opaque ComplianceOfficer role."""
    return TEST_USERS["compliance_officer_headers"]


# --------------------------------------------------------------------------
# Layer 1 — per-endpoint setup wrappers
# --------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> Dict[str, Any]:
    """Move the logical UTC clock. Returns the clock payload with `current_utc`."""
    return get_success_data(
        api_client.set_current_utc(_f.set_clock_payload(to_iso8601), regulator_headers())
    )


def new_state_program(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_state_program(
            _f.create_state_program_payload(**overrides), regulator_headers()
        )
    )


def new_wholesaler(state_program_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_wholesaler(
            _f.create_wholesaler_payload(state_program_id, **overrides), regulator_headers()
        )
    )


def set_license_status(wholesaler_id: str, license_status: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.set_wholesaler_license_status(
            wholesaler_id, _f.set_license_status_payload(license_status), regulator_headers()
        )
    )


def new_licensee_user(
    wholesaler_id: str, user_role: str = "FILING_AGENT", **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_licensee_user(
            _f.create_licensee_user_payload(wholesaler_id, user_role, **overrides),
            regulator_headers(),
        )
    )


def new_filing_agent(
    wholesaler_id: str, full_name: str = TEST_DEFAULTS["FILING_AGENT_NAME"], **overrides: Any
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Register a FILING_AGENT and return (user, headers built from its own id)."""
    user = new_licensee_user(
        wholesaler_id, "FILING_AGENT", full_name=full_name, **overrides
    )
    return user, make_filing_agent_headers(user["id"])


def new_certifying_officer(
    wholesaler_id: str,
    full_name: str = TEST_DEFAULTS["CERTIFYING_OFFICER_NAME"],
    **overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Register a CERTIFYING_OFFICER and return (user, headers built from its own id)."""
    user = new_licensee_user(
        wholesaler_id, "CERTIFYING_OFFICER", full_name=full_name, **overrides
    )
    return user, make_certifying_officer_headers(user["id"])


def new_dual_role_user(
    wholesaler_id: str, full_name: str = "Dana Dual", **overrides: Any
) -> Dict[str, Any]:
    return new_licensee_user(wholesaler_id, "DUAL_ROLE", full_name=full_name, **overrides)


def new_brand(
    wholesaler_id: str, agent_headers: Dict[str, str], approve: bool = False, **overrides: Any
) -> Dict[str, Any]:
    """File a brand registration; optionally approve it in the same step."""
    brand = get_success_data(
        api_client.create_brand(
            _f.create_brand_payload(wholesaler_id, **overrides), agent_headers
        )
    )
    if approve:
        brand = approve_brand(brand["id"])
    return brand


def approve_brand(brand_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.approve_brand(brand_id, regulator_headers()))


def reject_brand(brand_id: str, rejection_reason: Optional[str] = None) -> Dict[str, Any]:
    payload = (
        _f.reject_brand_payload(rejection_reason)
        if rejection_reason is not None
        else _f.reject_brand_payload()
    )
    return get_success_data(api_client.reject_brand(brand_id, payload, regulator_headers()))


def new_schedule(
    wholesaler_id: str,
    state_program_id: str,
    agent_headers: Dict[str, str],
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_price_schedule(
            _f.create_price_schedule_payload(wholesaler_id, state_program_id, **overrides),
            agent_headers,
        )
    )


def new_item(
    schedule_id: str, brand_id: str, agent_headers: Dict[str, str], **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_price_schedule_item(
            _f.create_price_schedule_item_payload(schedule_id, brand_id, **overrides),
            agent_headers,
        )
    )


def submit_schedule(schedule_id: str, agent_headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(
        api_client.submit_price_schedule(schedule_id, agent_headers)
    )


def certify_schedule(schedule_id: str, certifier_headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(
        api_client.certify_price_schedule(schedule_id, certifier_headers)
    )


def withdraw_schedule(schedule_id: str, agent_headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(
        api_client.withdraw_price_schedule(schedule_id, agent_headers)
    )


def return_schedule_for_correction(
    schedule_id: str, return_reason: Optional[str] = None
) -> Dict[str, Any]:
    payload = (
        _f.return_for_correction_payload(return_reason)
        if return_reason is not None
        else _f.return_for_correction_payload()
    )
    return get_success_data(
        api_client.return_price_schedule_for_correction(
            schedule_id, payload, regulator_headers()
        )
    )


def new_tier(
    item_id: str,
    agent_headers: Dict[str, str],
    min_cases: int = 5,
    discount_pct: float = 0.10,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_quantity_discount_tier(
            _f.create_quantity_discount_tier_payload(
                item_id, min_cases, discount_pct, **overrides
            ),
            agent_headers,
        )
    )


def new_combination(
    schedule_id: str,
    member_item_ids: Sequence[str],
    combined_case_price_cents: int,
    agent_headers: Dict[str, str],
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_combination_sale(
            _f.create_combination_sale_payload(
                schedule_id, list(member_item_ids), combined_case_price_cents, **overrides
            ),
            agent_headers,
        )
    )


def new_amendment(
    amending_item_id: str,
    reference_item_id: str,
    new_case_price_cents: int,
    new_unit_price_cents: int,
    expected_schedule_version: int,
    agent_headers: Dict[str, str],
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_hold_amendment(
            _f.create_hold_amendment_payload(
                amending_item_id,
                reference_item_id,
                new_case_price_cents,
                new_unit_price_cents,
                expected_schedule_version,
            ),
            agent_headers,
        )
    )


def accept_amendment(amendment_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.accept_hold_amendment(amendment_id, regulator_headers())
    )


def reject_amendment(amendment_id: str, rejection_reason: Optional[str] = None) -> Dict[str, Any]:
    payload = (
        _f.reject_hold_amendment_payload(rejection_reason)
        if rejection_reason is not None
        else _f.reject_hold_amendment_payload()
    )
    return get_success_data(
        api_client.reject_hold_amendment(amendment_id, payload, regulator_headers())
    )


def revoke_amendment(amendment_id: str, revocation_reason: Optional[str] = None) -> Dict[str, Any]:
    payload = (
        _f.revoke_hold_amendment_payload(revocation_reason)
        if revocation_reason is not None
        else _f.revoke_hold_amendment_payload()
    )
    return get_success_data(
        api_client.revoke_hold_amendment(amendment_id, payload, regulator_headers())
    )


def new_correction(
    item_id: str,
    corrected_case_price_cents: int,
    corrected_unit_price_cents: int,
    agent_headers: Dict[str, str],
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    payload = _f.create_error_correction_payload(
        item_id,
        corrected_case_price_cents,
        corrected_unit_price_cents,
        **({"reason": reason} if reason is not None else {}),
    )
    return get_success_data(api_client.create_error_correction(payload, agent_headers))


def approve_correction(correction_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.approve_error_correction(correction_id, regulator_headers())
    )


def deny_correction(correction_id: str, denial_reason: Optional[str] = None) -> Dict[str, Any]:
    payload = (
        _f.deny_error_correction_payload(denial_reason)
        if denial_reason is not None
        else _f.deny_error_correction_payload()
    )
    return get_success_data(
        api_client.deny_error_correction(correction_id, payload, regulator_headers())
    )


def new_invoice(
    wholesaler_id: str, invoice_date: str, agent_headers: Dict[str, str], **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_retailer_invoice(
            _f.create_retailer_invoice_payload(wholesaler_id, invoice_date, **overrides),
            agent_headers,
        )
    )


def new_invoice_line(
    invoice_id: str,
    item_id: str,
    case_price_charged_cents: int,
    unit_price_charged_cents: int,
    agent_headers: Dict[str, str],
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_invoice_line(
            _f.create_invoice_line_payload(
                invoice_id,
                item_id,
                case_price_charged_cents,
                unit_price_charged_cents,
                **overrides,
            ),
            agent_headers,
        )
    )


def validate_invoice(invoice_id: str, agent_headers: Dict[str, str]) -> Dict[str, Any]:
    return get_success_data(
        api_client.validate_retailer_invoice(invoice_id, agent_headers)
    )


def new_audit(
    wholesaler_id: str,
    state_program_id: str,
    audit_period_month: str,
    expected_wholesaler_version: Optional[int] = None,
) -> Dict[str, Any]:
    if expected_wholesaler_version is None:
        expected_wholesaler_version = wholesaler_version(wholesaler_id)
    return get_success_data(
        api_client.create_compliance_audit(
            _f.create_compliance_audit_payload(
                wholesaler_id, state_program_id, audit_period_month,
                expected_wholesaler_version,
            ),
            regulator_headers(),
        )
    )


def collect_audit(audit_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.collect_compliance_audit(audit_id, regulator_headers())
    )


def assess_audit(audit_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.assess_compliance_audit(audit_id, regulator_headers())
    )


def close_audit(audit_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.close_compliance_audit(audit_id, regulator_headers())
    )


def void_audit(audit_id: str, void_reason: Optional[str] = None) -> Dict[str, Any]:
    payload = (
        _f.void_compliance_audit_payload(void_reason)
        if void_reason is not None
        else _f.void_compliance_audit_payload()
    )
    return get_success_data(
        api_client.void_compliance_audit(audit_id, payload, regulator_headers())
    )


def run_posting(state_program_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_posting_run(
            _f.create_posting_run_payload(state_program_id), regulator_headers()
        )
    )


# --------------------------------------------------------------------------
# Read-back helpers
# --------------------------------------------------------------------------

def read_schedule(schedule_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_price_schedule(schedule_id, regulator_headers()))


def read_item(item_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_price_schedule_item(item_id, regulator_headers())
    )


def read_tier(tier_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_quantity_discount_tier(tier_id, regulator_headers())
    )


def read_combination(combination_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_combination_sale(combination_id, regulator_headers())
    )


def read_amendment(amendment_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_hold_amendment(amendment_id, regulator_headers()))


def read_correction(correction_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_error_correction(correction_id, regulator_headers())
    )


def read_wholesaler(wholesaler_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_wholesaler(wholesaler_id, regulator_headers()))


def read_brand(brand_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_brand(brand_id, regulator_headers()))


def read_invoice(invoice_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_retailer_invoice(invoice_id, regulator_headers())
    )


def read_invoice_line(line_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_invoice_line(line_id, regulator_headers()))


def read_audit(audit_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_compliance_audit(audit_id, regulator_headers()))


def read_exposure(wholesaler_id: str, variant: Optional[str] = None) -> Dict[str, Any]:
    params = {"variant": variant} if variant is not None else None
    return get_success_data(
        api_client.get_penalty_exposure(wholesaler_id, regulator_headers(), params=params)
    )


def read_posted_price(
    item_id: str, variant: Optional[str] = None, as_of: Optional[str] = None
) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    if variant is not None:
        params["variant"] = variant
    if as_of is not None:
        params["as_of"] = as_of
    return get_success_data(
        api_client.get_posted_price(item_id, regulator_headers(), params=params or None)
    )


def schedule_version(schedule_id: str) -> int:
    return read_schedule(schedule_id)["version"]


def wholesaler_version(wholesaler_id: str) -> int:
    return read_wholesaler(wholesaler_id)["version"]


def list_findings(audit_id: str) -> List[Dict[str, Any]]:
    body = get_success_data(
        api_client.list_audit_findings(regulator_headers(), params={"audit_id": audit_id})
    )
    return body


# --------------------------------------------------------------------------
# Layer 2 — scene builders
# --------------------------------------------------------------------------

def setup_licensee_base(
    clock: Optional[str] = "2026-08-01T00:00:00Z",
    program_overrides: Optional[Dict[str, Any]] = None,
    license_number: str = TEST_DEFAULTS["LICENSE_NUMBER_A"],
    legal_name: str = TEST_DEFAULTS["LEGAL_NAME_A"],
    with_certifier: bool = True,
    with_brand: bool = True,
    approve_brand_registration: bool = True,
    brand_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Clock + program + wholesaler + filing agent (+ certifying officer, + brand).

    Returns a dict with `program`, `wholesaler`, `agent`, `agent_headers`,
    and when requested `certifier`, `certifier_headers` and `brand`.
    """
    if clock is not None:
        set_clock(clock)
    program = new_state_program(**(program_overrides or {}))
    wholesaler = new_wholesaler(
        program["id"], license_number=license_number, legal_name=legal_name
    )
    agent, agent_headers = new_filing_agent(wholesaler["id"])

    scene: Dict[str, Any] = {
        "program": program,
        "wholesaler": wholesaler,
        "agent": agent,
        "agent_headers": agent_headers,
    }

    if with_certifier:
        certifier, certifier_headers = new_certifying_officer(wholesaler["id"])
        scene["certifier"] = certifier
        scene["certifier_headers"] = certifier_headers

    if with_brand:
        scene["brand"] = new_brand(
            wholesaler["id"],
            agent_headers,
            approve=approve_brand_registration,
            **(brand_overrides or {}),
        )

    return scene


DEFAULT_ITEM_SPECS: List[Dict[str, Any]] = [
    {
        "size_ml": TEST_DEFAULTS["SIZE_ML"],
        "bottles_per_case": TEST_DEFAULTS["BOTTLES_PER_CASE"],
        "case_price_cents": TEST_DEFAULTS["CASE_PRICE_CENTS"],
        "unit_price_cents": TEST_DEFAULTS["UNIT_PRICE_CENTS"],
    }
]


def setup_draft_schedule(
    scene: Dict[str, Any],
    posting_month: str = TEST_DEFAULTS["POSTING_MONTH"],
    item_specs: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Open a DRAFT schedule on an existing scene and attach items to it.

    Adds `schedule` and `items` to the scene and returns the same dict.
    """
    schedule = new_schedule(
        scene["wholesaler"]["id"],
        scene["program"]["id"],
        scene["agent_headers"],
        posting_month=posting_month,
    )
    specs = DEFAULT_ITEM_SPECS if item_specs is None else item_specs
    items = [
        new_item(schedule["id"], scene["brand"]["id"], scene["agent_headers"], **spec)
        for spec in specs
    ]
    scene["schedule"] = schedule
    scene["items"] = items
    return scene


def setup_submitted_schedule(
    posting_month: str = TEST_DEFAULTS["POSTING_MONTH"],
    item_specs: Optional[List[Dict[str, Any]]] = None,
    **base_kwargs: Any,
) -> Dict[str, Any]:
    """Whole chain from clock through `DRAFT → SUBMITTED`."""
    scene = setup_licensee_base(**base_kwargs)
    setup_draft_schedule(scene, posting_month=posting_month, item_specs=item_specs)
    scene["schedule"] = submit_schedule(scene["schedule"]["id"], scene["agent_headers"])
    return scene


def setup_certified_schedule(
    posting_month: str = TEST_DEFAULTS["POSTING_MONTH"],
    item_specs: Optional[List[Dict[str, Any]]] = None,
    **base_kwargs: Any,
) -> Dict[str, Any]:
    """Whole chain from clock through `SUBMITTED → POSTED`.

    After this the schedule is inside its post-and-hold window and every item is
    `POSTED` with its certified price snapshot written.
    """
    scene = setup_submitted_schedule(
        posting_month=posting_month, item_specs=item_specs, **base_kwargs
    )
    scene["schedule"] = certify_schedule(
        scene["schedule"]["id"], scene["certifier_headers"]
    )
    scene["items"] = [read_item(item["id"]) for item in scene["items"]]
    return scene


def setup_effective_schedule(
    posting_month: str = TEST_DEFAULTS["POSTING_MONTH"],
    item_specs: Optional[List[Dict[str, Any]]] = None,
    clock_before_run: str = "2026-10-01T00:00:00Z",
    **base_kwargs: Any,
) -> Dict[str, Any]:
    """Certified schedule, clock advanced past the effective date, then a posting run.

    Adds `posting_run` to the scene; the schedule and its items come back `EFFECTIVE`.
    """
    scene = setup_certified_schedule(
        posting_month=posting_month, item_specs=item_specs, **base_kwargs
    )
    set_clock(clock_before_run)
    scene["posting_run"] = run_posting(scene["program"]["id"])
    scene["schedule"] = read_schedule(scene["schedule"]["id"])
    scene["items"] = [read_item(item["id"]) for item in scene["items"]]
    return scene


def setup_two_wholesalers_certified(
    clock: str = "2026-08-01T00:00:00Z",
    program_overrides: Optional[Dict[str, Any]] = None,
    posting_month: str = TEST_DEFAULTS["POSTING_MONTH"],
    item_a_specs: Optional[List[Dict[str, Any]]] = None,
    item_b_spec: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Two wholesalers of one program, each with a certified schedule on the same key.

    Wholesaler A's first item and wholesaler B's item share the posting key, so a
    hold amendment by A may reference B's item. Returns a dict with `program`,
    `wholesaler_a`, `wholesaler_b`, `agent_a`, `agent_a_headers`, `certifier_a`,
    `certifier_a_headers`, the same four for B, `brand_a`, `brand_b`,
    `schedule_a`, `items_a`, `schedule_b` and `item_b`.
    """
    set_clock(clock)
    program = new_state_program(**(program_overrides or {}))

    wholesaler_a = new_wholesaler(
        program["id"],
        license_number=TEST_DEFAULTS["LICENSE_NUMBER_A"],
        legal_name=TEST_DEFAULTS["LEGAL_NAME_A"],
    )
    wholesaler_b = new_wholesaler(
        program["id"],
        license_number=TEST_DEFAULTS["LICENSE_NUMBER_B"],
        legal_name=TEST_DEFAULTS["LEGAL_NAME_B"],
    )

    agent_a, agent_a_headers = new_filing_agent(wholesaler_a["id"], "Fay Filer")
    certifier_a, certifier_a_headers = new_certifying_officer(
        wholesaler_a["id"], "Cora Certifier"
    )
    agent_b, agent_b_headers = new_filing_agent(wholesaler_b["id"], "Ben Filer")
    certifier_b, certifier_b_headers = new_certifying_officer(
        wholesaler_b["id"], "Bea Certifier"
    )

    brand_a = new_brand(wholesaler_a["id"], agent_a_headers, approve=True)
    brand_b = new_brand(wholesaler_b["id"], agent_b_headers, approve=True)

    schedule_a = new_schedule(
        wholesaler_a["id"], program["id"], agent_a_headers, posting_month=posting_month
    )
    specs_a = DEFAULT_ITEM_SPECS if item_a_specs is None else item_a_specs
    items_a = [
        new_item(schedule_a["id"], brand_a["id"], agent_a_headers, **spec) for spec in specs_a
    ]
    submit_schedule(schedule_a["id"], agent_a_headers)
    schedule_a = certify_schedule(schedule_a["id"], certifier_a_headers)

    schedule_b = new_schedule(
        wholesaler_b["id"], program["id"], agent_b_headers, posting_month=posting_month
    )
    spec_b = item_b_spec or {
        "size_ml": TEST_DEFAULTS["SIZE_ML"],
        "bottles_per_case": TEST_DEFAULTS["BOTTLES_PER_CASE"],
        "case_price_cents": 110_000,
        "unit_price_cents": 10_000,
    }
    item_b = new_item(schedule_b["id"], brand_b["id"], agent_b_headers, **spec_b)
    submit_schedule(schedule_b["id"], agent_b_headers)
    schedule_b = certify_schedule(schedule_b["id"], certifier_b_headers)

    return {
        "program": program,
        "wholesaler_a": wholesaler_a,
        "wholesaler_b": wholesaler_b,
        "agent_a": agent_a,
        "agent_a_headers": agent_a_headers,
        "certifier_a": certifier_a,
        "certifier_a_headers": certifier_a_headers,
        "agent_b": agent_b,
        "agent_b_headers": agent_b_headers,
        "certifier_b": certifier_b,
        "certifier_b_headers": certifier_b_headers,
        "brand_a": brand_a,
        "brand_b": brand_b,
        "schedule_a": read_schedule(schedule_a["id"]),
        "items_a": [read_item(item["id"]) for item in items_a],
        "schedule_b": read_schedule(schedule_b["id"]),
        "item_b": read_item(item_b["id"]),
    }


def setup_pending_amendment(
    new_case_price_cents: int = 115_000,
    new_unit_price_cents: int = 10_500,
    **scene_kwargs: Any,
) -> Dict[str, Any]:
    """Two-wholesaler scene plus one `PENDING` hold amendment by A referencing B."""
    scene = setup_two_wholesalers_certified(**scene_kwargs)
    amendment = new_amendment(
        scene["items_a"][0]["id"],
        scene["item_b"]["id"],
        new_case_price_cents,
        new_unit_price_cents,
        schedule_version(scene["schedule_a"]["id"]),
        scene["agent_a_headers"],
    )
    scene["amendment"] = amendment
    return scene


def setup_invoice_with_lines(
    scene: Dict[str, Any],
    invoice_date: str,
    line_specs: List[Dict[str, Any]],
    validate: bool = True,
    wholesaler_key: str = "wholesaler",
    agent_key: str = "agent_headers",
) -> Dict[str, Any]:
    """Open an invoice on an existing scene, attach lines, optionally validate it.

    Each entry of `line_specs` is a kwargs dict for `new_invoice_line` and must
    carry `item_id`, `case_price_charged_cents` and `unit_price_charged_cents`.
    Adds `invoice` and `lines` to the scene.
    """
    agent_headers = scene[agent_key]
    invoice = new_invoice(scene[wholesaler_key]["id"], invoice_date, agent_headers)
    lines = []
    for spec in line_specs:
        spec = dict(spec)
        item_id = spec.pop("item_id")
        case_price = spec.pop("case_price_charged_cents")
        unit_price = spec.pop("unit_price_charged_cents")
        lines.append(
            new_invoice_line(invoice["id"], item_id, case_price, unit_price, agent_headers, **spec)
        )
    if validate:
        invoice = validate_invoice(invoice["id"], agent_headers)
        lines = [read_invoice_line(line["id"]) for line in lines]
    scene["invoice"] = invoice
    scene["lines"] = lines
    return scene


def setup_flagged_invoice(
    posting_month: str = TEST_DEFAULTS["POSTING_MONTH"],
    item_specs: Optional[List[Dict[str, Any]]] = None,
    clock_before_run: str = "2026-10-01T00:00:00Z",
    invoice_date: str = "2026-10-05T00:00:00Z",
    line_specs: Optional[List[Dict[str, Any]]] = None,
    program_overrides: Optional[Dict[str, Any]] = None,
    **base_kwargs: Any,
) -> Dict[str, Any]:
    """Effective schedule, then one validated invoice whose single line is off posted.

    By default the line charges 5,000 cents per case less than the posted price on a
    single case, so the invoice validates to `FLAGGED`.
    """
    scene = setup_effective_schedule(
        posting_month=posting_month,
        item_specs=item_specs,
        clock_before_run=clock_before_run,
        program_overrides=program_overrides,
        **base_kwargs,
    )
    if line_specs is None:
        line_specs = [
            {
                "item_id": scene["items"][0]["id"],
                "cases_quantity": 1,
                "case_price_charged_cents": scene["items"][0]["case_price_cents"] - 5_000,
                "unit_price_charged_cents": scene["items"][0]["unit_price_cents"],
            }
        ]
    return setup_invoice_with_lines(scene, invoice_date, line_specs, validate=True)


def setup_collected_audit(
    audit_period_month: str = "2026-10",
    **flagged_kwargs: Any,
) -> Dict[str, Any]:
    """Flagged invoice scene, then an audit taken from `OPEN` to `COLLECTED`."""
    scene = setup_flagged_invoice(**flagged_kwargs)
    audit = new_audit(
        scene["wholesaler"]["id"], scene["program"]["id"], audit_period_month
    )
    scene["audit"] = collect_audit(audit["id"])
    scene["invoice"] = read_invoice(scene["invoice"]["id"])
    return scene


def setup_assessed_audit(
    audit_period_month: str = "2026-10",
    **flagged_kwargs: Any,
) -> Dict[str, Any]:
    """Flagged invoice scene, then an audit taken from `OPEN` through `ASSESSED`."""
    scene = setup_collected_audit(audit_period_month=audit_period_month, **flagged_kwargs)
    scene["audit"] = assess_audit(scene["audit"]["id"])
    scene["invoice"] = read_invoice(scene["invoice"]["id"])
    scene["wholesaler"] = read_wholesaler(scene["wholesaler"]["id"])
    return scene


def setup_schedule_with_correction_quota_used(
    approved_corrections: int = 1,
    posting_month: str = TEST_DEFAULTS["POSTING_MONTH"],
    program_overrides: Optional[Dict[str, Any]] = None,
    **base_kwargs: Any,
) -> Dict[str, Any]:
    """Certified schedule carrying two items, with `approved_corrections` already approved.

    Each approved correction is filed against its own item so the schedule's
    `correction_count` advances one step at a time. Adds `corrections` to the scene.
    """
    item_specs = [
        {
            "size_ml": 750, "bottles_per_case": 12,
            "case_price_cents": 120_000, "unit_price_cents": 11_000,
        },
        {
            "size_ml": 1000, "bottles_per_case": 12,
            "case_price_cents": 150_000, "unit_price_cents": 13_000,
        },
        {
            "size_ml": 375, "bottles_per_case": 24,
            "case_price_cents": 30_000, "unit_price_cents": 1_500,
        },
    ]
    scene = setup_certified_schedule(
        posting_month=posting_month,
        item_specs=item_specs,
        program_overrides=program_overrides,
        **base_kwargs,
    )
    corrections = []
    for index in range(approved_corrections):
        item = scene["items"][index]
        correction = new_correction(
            item["id"],
            item["case_price_cents"] - 1_000,
            item["unit_price_cents"] - 100,
            scene["agent_headers"],
        )
        corrections.append(approve_correction(correction["id"]))
    scene["corrections"] = corrections
    scene["schedule"] = read_schedule(scene["schedule"]["id"])
    scene["items"] = [read_item(item["id"]) for item in scene["items"]]
    return scene
