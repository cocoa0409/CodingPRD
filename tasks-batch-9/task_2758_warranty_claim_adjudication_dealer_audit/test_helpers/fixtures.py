"""Composite setup helpers.

Every helper drives the real endpoints declared by the PRD and uses the lenient
get_success_data() validator, so a broken precondition surfaces as a setup failure
rather than as a confusing assertion inside a test.

Dealer-side calls always thread the real Dealer id through
make_dealer_warranty_admin_headers(), because PRD §2.1 makes X-User-ID the id of the
acting dealership's Dealer row for a DealerWarrantyAdmin.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories as payloads
from .api_client import api_client
from .constants import DEFAULT_CLOCK_INSTANT, OPERATORS
from .test_users import TEST_USERS, make_dealer_warranty_admin_headers

ADMIN = TEST_USERS["warranty_admin_headers"]
ADJUDICATOR = TEST_USERS["claim_adjudicator_headers"]
ADJUDICATOR_ALT = TEST_USERS["claim_adjudicator_alt_headers"]
MANAGER = TEST_USERS["adjudication_manager_headers"]
FIELD_AUDITOR = TEST_USERS["field_auditor_headers"]
AUDIT_MANAGER = TEST_USERS["audit_manager_headers"]
APPEAL_REVIEWER = TEST_USERS["appeal_reviewer_headers"]


# --- Logical clock ---------------------------------------------------------


def set_clock(current_utc: str = DEFAULT_CLOCK_INSTANT) -> dict:
    """Set the server's logical clock (PRD §2.6)."""
    return get_success_data(
        api_client.set_clock(payloads.set_clock_payload(current_utc), ADMIN)
    )


# --- Reference data --------------------------------------------------------


def create_state_law_profile(**overrides) -> dict:
    return get_success_data(
        api_client.create_state_law_profile(
            payloads.create_state_law_profile_payload(**overrides), ADMIN
        )
    )


def create_dealer(state_law_profile_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_dealer(
            payloads.create_dealer_payload(
                state_law_profile_id=state_law_profile_id, **overrides
            ),
            ADMIN,
        )
    )


def create_vehicle(**overrides) -> dict:
    return get_success_data(
        api_client.create_vehicle(payloads.create_vehicle_payload(**overrides), ADMIN)
    )


def create_labor_operation(**overrides) -> dict:
    return get_success_data(
        api_client.create_labor_operation(
            payloads.create_labor_operation_payload(**overrides), ADMIN
        )
    )


def create_part(**overrides) -> dict:
    return get_success_data(
        api_client.create_part(payloads.create_part_payload(**overrides), ADMIN)
    )


def setup_reference_data(
    profile_overrides=None,
    dealer_overrides=None,
    vehicle_overrides=None,
    operation_overrides=None,
    part_overrides=None,
    with_part=True,
) -> dict:
    """Publish one state law profile, dealer, vehicle, labor operation and part.

    Returns a world dict with keys: profile, dealer, vehicle, operation, part and
    dealer_headers.
    """
    profile = create_state_law_profile(**(profile_overrides or {}))
    dealer = create_dealer(profile["id"], **(dealer_overrides or {}))
    vehicle = create_vehicle(**(vehicle_overrides or {}))
    operation = create_labor_operation(**(operation_overrides or {}))
    part = create_part(**(part_overrides or {})) if with_part else None
    if operation.get("requires_causal_part") and part is not None:
        assert part["failure_group"] == operation["causal_failure_group"], (
            "the causal part's failure_group must equal the operation's "
            "causal_failure_group for the part to be admissible"
        )
    return {
        "profile": profile,
        "dealer": dealer,
        "vehicle": vehicle,
        "operation": operation,
        "part": part,
        "dealer_headers": make_dealer_warranty_admin_headers(dealer["id"]),
    }


# --- Reads -----------------------------------------------------------------


def get_dealer(dealer_id: str) -> dict:
    return get_success_data(api_client.get_dealer(dealer_id, ADMIN))


def get_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_claim(claim_id, ADMIN))


def get_audit(audit_id: str) -> dict:
    return get_success_data(api_client.get_audit(audit_id, ADMIN))


def get_finding(finding_id: str) -> dict:
    return get_success_data(api_client.get_audit_finding(finding_id, ADMIN))


def get_appeal(appeal_id: str) -> dict:
    return get_success_data(api_client.get_appeal(appeal_id, ADMIN))


def get_goodwill(authorization_id: str) -> dict:
    return get_success_data(
        api_client.get_goodwill_authorization(authorization_id, ADMIN)
    )


def get_parts_return(parts_return_id: str) -> dict:
    return get_success_data(api_client.get_parts_return(parts_return_id, ADMIN))


def list_claim_edits(claim_id: str, params=None) -> list:
    return get_success_data(
        api_client.list_claim_edits(claim_id, ADMIN, params=params)
    )


def list_ledger_entries(dealer_id: str, params=None) -> list:
    return get_success_data(
        api_client.list_dealer_ledger_entries(dealer_id, ADMIN, params=params)
    )


def list_parts_returns(params=None) -> list:
    return get_success_data(api_client.list_parts_returns(ADMIN, params=params))


def parts_return_for_claim(claim_id: str) -> dict:
    rows = list_parts_returns({"claim_id": claim_id})
    assert rows, f"expected a parts-return obligation for claim {claim_id}"
    return rows[0]


# --- Claim intake and lifecycle -------------------------------------------


def submit_claim(world: dict, **overrides) -> dict:
    """Submit one claim against the world's dealer, vehicle, operation and part."""
    part = world.get("part")
    fields = {
        "dealer_id": world["dealer"]["id"],
        "vehicle_id": world["vehicle"]["id"],
        "labor_operation_id": world["operation"]["id"],
        "causal_part_id": part["id"] if part is not None else None,
        # An explicit override wins over the world's own reference data, so a caller may
        # point one submission at a different vehicle, operation or part.
        **overrides,
    }
    payload = payloads.create_claim_payload(**fields)
    headers = world.get("dealer_headers") or make_dealer_warranty_admin_headers(
        world["dealer"]["id"]
    )
    return get_success_data(api_client.create_claim(payload, headers))


def setup_claim(
    profile_overrides=None,
    dealer_overrides=None,
    vehicle_overrides=None,
    operation_overrides=None,
    part_overrides=None,
    with_part=True,
    claim_overrides=None,
) -> dict:
    """Reference data plus one submitted claim. Returns the world with key `claim`."""
    world = setup_reference_data(
        profile_overrides=profile_overrides,
        dealer_overrides=dealer_overrides,
        vehicle_overrides=vehicle_overrides,
        operation_overrides=operation_overrides,
        part_overrides=part_overrides,
        with_part=with_part,
    )
    world["claim"] = submit_claim(world, **(claim_overrides or {}))
    return world


def resubmit_claim(world: dict, claim_id: str = None, **overrides) -> dict:
    claim_id = claim_id or world["claim"]["id"]
    headers = world.get("dealer_headers") or make_dealer_warranty_admin_headers(
        world["dealer"]["id"]
    )
    return get_success_data(
        api_client.resubmit_claim(
            claim_id, payloads.resubmit_claim_payload(**overrides), headers
        )
    )


def approve_claim(claim_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.adjudicate_claim(
            claim_id,
            payloads.adjudicate_claim_payload(decision="APPROVE", **overrides),
            headers or ADJUDICATOR,
        )
    )


def deny_claim(claim_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.adjudicate_claim(
            claim_id,
            payloads.adjudicate_claim_payload(decision="DENY", **overrides),
            headers or ADJUDICATOR,
        )
    )


def void_claim(claim_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.void_claim(
            claim_id, payloads.void_claim_payload(**overrides), headers or ADMIN
        )
    )


def pay_claim(claim_id: str) -> dict:
    return get_success_data(api_client.pay_claim(claim_id, ADMIN))


def setup_approved_claim(approve_overrides=None, **setup_kwargs) -> dict:
    """World with its claim adjudicated APPROVED."""
    world = setup_claim(**setup_kwargs)
    world["claim"] = approve_claim(world["claim"]["id"], **(approve_overrides or {}))
    return world


def setup_paid_claim(approve_overrides=None, **setup_kwargs) -> dict:
    """World with its claim adjudicated APPROVED and then paid."""
    world = setup_approved_claim(approve_overrides=approve_overrides, **setup_kwargs)
    world["claim"] = pay_claim(world["claim"]["id"])
    return world


# --- Goodwill authority ---------------------------------------------------


def raise_goodwill(claim: dict, headers=None, **overrides) -> dict:
    """Raise a goodwill authorization against a claim whose coverage_type is NONE."""
    overrides.setdefault("expected_claim_version", claim["version"])
    return get_success_data(
        api_client.create_goodwill_authorization(
            claim["id"],
            payloads.create_goodwill_authorization_payload(**overrides),
            headers or ADJUDICATOR,
        )
    )


def decide_goodwill(authorization_id: str, action="APPROVE", headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.decide_goodwill_authorization(
            authorization_id,
            payloads.decide_goodwill_authorization_payload(action=action, **overrides),
            headers or ADJUDICATOR_ALT,
        )
    )


def setup_out_of_warranty_claim(
    odometer_at_repair=60000,
    repair_date="2026-03-10",
    claim_overrides=None,
    **setup_kwargs,
) -> dict:
    """A claim whose coverage_type is NONE, i.e. beyond the vehicle's basic terms.

    The default odometer sits past the vehicle's basic_miles, so coverage determination
    finds neither powertrain nor basic terms satisfied.
    """
    overrides = dict(claim_overrides or {})
    overrides.setdefault("odometer_at_repair", odometer_at_repair)
    overrides.setdefault("repair_date", repair_date)
    return setup_claim(claim_overrides=overrides, **setup_kwargs)


# --- Parts return program -------------------------------------------------


def receive_part(parts_return_id: str, received_date: str) -> dict:
    return get_success_data(
        api_client.receive_parts_return(
            parts_return_id, payloads.receive_parts_return_payload(received_date), ADMIN
        )
    )


def analyze_part(parts_return_id: str, analysis_result="DEFECT_CONFIRMED", **overrides) -> dict:
    return get_success_data(
        api_client.analyze_parts_return(
            parts_return_id,
            payloads.analyze_parts_return_payload(
                analysis_result=analysis_result, **overrides
            ),
            ADMIN,
        )
    )


def run_non_return_sweep() -> dict:
    return get_success_data(api_client.run_non_return_sweep(ADMIN))


def setup_returnable_claim_world(
    retention_days=30,
    part_overrides=None,
    **setup_kwargs,
) -> dict:
    """A world whose causal part requires return, so submission raises an obligation."""
    overrides = dict(part_overrides or {})
    overrides.setdefault("return_required", True)
    overrides.setdefault("retention_days", retention_days)
    world = setup_claim(part_overrides=overrides, **setup_kwargs)
    world["parts_return"] = parts_return_for_claim(world["claim"]["id"])
    return world


# --- Labor rate petitions -------------------------------------------------


def create_rate_request(dealer: dict, headers=None, **overrides) -> dict:
    overrides.setdefault("expected_dealer_version", dealer["version"])
    return get_success_data(
        api_client.create_labor_rate_request(
            payloads.create_labor_rate_request_payload(
                dealer_id=dealer["id"], **overrides
            ),
            headers or make_dealer_warranty_admin_headers(dealer["id"]),
        )
    )


def review_rate_request(request_id: str, action="START_REVIEW", **overrides) -> dict:
    return get_success_data(
        api_client.review_labor_rate_request(
            request_id,
            payloads.review_labor_rate_request_payload(action=action, **overrides),
            ADMIN,
        )
    )


def decide_rate_request(request_id: str, action="APPROVE", headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.decide_labor_rate_request(
            request_id,
            payloads.decide_labor_rate_request_payload(action=action, **overrides),
            headers or MANAGER,
        )
    )


def run_deemed_approval() -> dict:
    return get_success_data(api_client.run_deemed_approval(ADMIN))


# --- Dealer audits --------------------------------------------------------


def schedule_audit(dealer: dict, **overrides) -> dict:
    overrides.setdefault("expected_dealer_version", dealer["version"])
    return get_success_data(
        api_client.create_audit(
            payloads.create_audit_payload(dealer_id=dealer["id"], **overrides),
            AUDIT_MANAGER,
        )
    )


def start_audit(audit_id: str, headers=None) -> dict:
    return get_success_data(api_client.start_audit(audit_id, headers or FIELD_AUDITOR))


def add_finding(audit_id: str, claim_id: str, unsupported_amount_cents: int, **overrides) -> dict:
    return get_success_data(
        api_client.create_audit_finding(
            audit_id,
            payloads.create_audit_finding_payload(
                claim_id=claim_id,
                unsupported_amount_cents=unsupported_amount_cents,
                **overrides,
            ),
            FIELD_AUDITOR,
        )
    )


def issue_findings(audit_id: str) -> dict:
    return get_success_data(api_client.issue_audit_findings(audit_id, AUDIT_MANAGER))


def close_audit(audit_id: str) -> dict:
    return get_success_data(api_client.close_audit(audit_id, AUDIT_MANAGER))


def file_appeal(audit: dict, contested_finding_ids, dealer_id: str = None, **overrides) -> dict:
    overrides.setdefault("expected_audit_version", audit["version"])
    dealer_id = dealer_id or audit["dealer_id"]
    return get_success_data(
        api_client.create_appeal(
            audit["id"],
            payloads.create_appeal_payload(
                contested_finding_ids=contested_finding_ids, **overrides
            ),
            make_dealer_warranty_admin_headers(dealer_id),
        )
    )


def decide_appeal(appeal_id: str, action="DENY", headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.decide_appeal(
            appeal_id,
            payloads.decide_appeal_payload(action=action, **overrides),
            headers or APPEAL_REVIEWER,
        )
    )


# --- Composite worlds -----------------------------------------------------


def setup_dealer_with_claims(
    claim_specs,
    profile_overrides=None,
    dealer_overrides=None,
    operation_overrides=None,
    part_overrides=None,
    with_part=True,
    vehicle_overrides=None,
) -> dict:
    """One dealer plus one claim per spec, each claim on its own vehicle.

    Giving every claim its own vehicle keeps the duplicate-repair-order and
    overlapping-repair rules of PRD §3.3 out of the way, so a caller can build several
    live claims for one dealer without engineering a collision.

    Each entry of `claim_specs` is a dict that may carry:
      "claim"   — overrides for the submission payload
      "approve" — overrides for the adjudication payload; when present the claim is
                  approved
      "pay"     — when true the approved claim is also paid
      "vehicle" — overrides for that claim's own vehicle
    Returns the world with keys claims (list) and vehicles (list).
    """
    profile = create_state_law_profile(**(profile_overrides or {}))
    dealer = create_dealer(profile["id"], **(dealer_overrides or {}))
    operation = create_labor_operation(**(operation_overrides or {}))
    part = create_part(**(part_overrides or {})) if with_part else None
    dealer_headers = make_dealer_warranty_admin_headers(dealer["id"])

    world = {
        "profile": profile,
        "dealer": dealer,
        "operation": operation,
        "part": part,
        "dealer_headers": dealer_headers,
        "vehicles": [],
        "claims": [],
    }

    for spec in claim_specs:
        vehicle = create_vehicle(**{**(vehicle_overrides or {}), **(spec.get("vehicle") or {})})
        world["vehicles"].append(vehicle)
        claim = submit_claim(
            {
                "dealer": dealer,
                "vehicle": vehicle,
                "operation": operation,
                "part": part,
                "dealer_headers": dealer_headers,
            },
            **(spec.get("claim") or {}),
        )
        if spec.get("approve") is not None:
            claim = approve_claim(claim["id"], **(spec.get("approve") or {}))
        if spec.get("pay"):
            claim = pay_claim(claim["id"])
        world["claims"].append(claim)

    world["dealer"] = get_dealer(dealer["id"])
    return world


def setup_audit_with_findings(
    claim_specs,
    finding_specs,
    audit_overrides=None,
    issue=False,
    **world_kwargs,
) -> dict:
    """Build paid claims, schedule an audit over them, go on site and attach findings.

    `finding_specs` is a list of dicts, each carrying "claim_index" and
    "unsupported_amount_cents" plus any finding payload overrides. When `issue` is true
    the audit's findings are issued as well.
    Returns the world with keys audit and findings.
    """
    world = setup_dealer_with_claims(claim_specs, **world_kwargs)
    audit = schedule_audit(world["dealer"], **(audit_overrides or {}))
    audit = start_audit(audit["id"])
    findings = []
    for spec in finding_specs:
        spec = dict(spec)
        claim_index = spec.pop("claim_index")
        amount = spec.pop("unsupported_amount_cents")
        findings.append(
            add_finding(audit["id"], world["claims"][claim_index]["id"], amount, **spec)
        )
    if issue:
        audit = issue_findings(audit["id"])
    world["audit"] = audit
    world["findings"] = findings
    world["dealer"] = get_dealer(world["dealer"]["id"])
    return world


def setup_appealed_audit(
    claim_specs,
    finding_specs,
    contested_indexes=None,
    audit_overrides=None,
    appeal_overrides=None,
    **world_kwargs,
) -> dict:
    """An audit whose findings were issued and then appealed by the dealer.

    Returns the world with keys audit, findings and appeal.
    """
    world = setup_audit_with_findings(
        claim_specs,
        finding_specs,
        audit_overrides=audit_overrides,
        issue=True,
        **world_kwargs,
    )
    indexes = contested_indexes if contested_indexes is not None else range(len(world["findings"]))
    contested = [world["findings"][i]["id"] for i in indexes]
    world["appeal"] = file_appeal(
        world["audit"], contested, world["dealer"]["id"], **(appeal_overrides or {})
    )
    world["audit"] = get_audit(world["audit"]["id"])
    return world


def setup_dealer_under_audit_hold(claim_specs=None, audit_overrides=None, **world_kwargs) -> dict:
    """A dealer whose audit_hold is true because one of its audits is IN_FIELD."""
    world = setup_dealer_with_claims(claim_specs or [], **world_kwargs)
    audit = schedule_audit(world["dealer"], **(audit_overrides or {}))
    world["audit"] = start_audit(audit["id"])
    world["dealer"] = get_dealer(world["dealer"]["id"])
    return world


def setup_second_dealer(world: dict, **overrides) -> dict:
    """Enroll a second dealer under the same state law profile as `world`.

    Used by the peer-comparison reads of PRD §3.9, where every dealer with vehicles in
    operation participates in the peer set.
    """
    dealer = create_dealer(world["profile"]["id"], **overrides)
    return {
        "profile": world["profile"],
        "dealer": dealer,
        "dealer_headers": make_dealer_warranty_admin_headers(dealer["id"]),
    }


def expense_analytics(dealer_id: str, params=None) -> dict:
    return get_success_data(
        api_client.get_dealer_expense_analytics(dealer_id, ADMIN, params=params)
    )


def setup_suspended_claim_by_posture(
    debit_claim_spec=None,
    sibling_claim_spec=None,
    retention_days=0,
    sweep_clock="2026-06-15T00:00:00Z",
    **world_kwargs,
) -> dict:
    """Drive a dealer's posture up with a non-return debit so a sibling claim is held.

    The first claim carries a return-required causal part, is approved and paid, and is
    then swept as not returned; the second claim is left in SUBMITTED so the posture
    cascade of PRD §3.7 appends a DEALER_POSTURE_HOLD edit to it.
    Returns the world with keys claims, parts_return and sweep.
    """
    part_overrides = dict(world_kwargs.pop("part_overrides", None) or {})
    part_overrides.setdefault("return_required", True)
    part_overrides.setdefault("retention_days", retention_days)
    specs = [
        {**(debit_claim_spec or {})},
        {**(sibling_claim_spec or {})},
    ]
    world = setup_dealer_with_claims(specs, part_overrides=part_overrides, **world_kwargs)
    world["parts_return"] = parts_return_for_claim(world["claims"][0]["id"])
    set_clock(sweep_clock)
    world["sweep"] = run_non_return_sweep()
    world["claims"] = [get_claim(claim["id"]) for claim in world["claims"]]
    world["dealer"] = get_dealer(world["dealer"]["id"])
    world["parts_return"] = get_parts_return(world["parts_return"]["id"])
    return world
