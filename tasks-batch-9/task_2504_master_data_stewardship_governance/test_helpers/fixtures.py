"""Composite setup helpers for the master data stewardship governance API.

Every helper here builds its preconditions from scratch through published
endpoints, because each test starts against an empty system. Helpers use the
lenient setup validator so a broken precondition reports as a setup failure
rather than as a confusing assertion error.

The central helper is :func:`setup_governed_domain`, which walks the whole
standing-up sequence — position the clock, define the domain, register the
accountable stewards, certify and register the contributing sources, define
the quality rules, activate — and returns a context dictionary that the more
specific helpers accept as their first argument.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK, TEST_DEFAULTS
from .factories import (
    change_request_payload,
    consumer_subscription_payload,
    domain_payload,
    master_record_payload,
    merge_proposal_payload,
    quality_rule_payload,
    source_registration_payload,
    source_system_payload,
    steward_assignment_payload,
    steward_payload,
)
from .test_users import (
    GOVERNANCE_ADMIN_HEADERS,
    make_consumer_rep_headers,
    make_data_owner_headers,
    make_data_steward_headers,
)

ADMIN = GOVERNANCE_ADMIN_HEADERS


# --------------------------------------------------------------------------
# Primitive steps
# --------------------------------------------------------------------------


def set_clock(to_iso8601: str = CLOCK) -> str:
    """Position the logical clock and return the reported position."""
    data = get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))
    return data["current_utc"]


def create_domain(**overrides) -> Dict[str, Any]:
    return get_success_data(api_client.create_domain(domain_payload(**overrides), ADMIN))


def read_domain(domain_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_domain(domain_id, ADMIN))


def domain_version(domain_id: str) -> int:
    """Re-read the domain and return its current version."""
    return read_domain(domain_id)["version"]


def create_steward(**overrides) -> Dict[str, Any]:
    return get_success_data(
        api_client.create_steward(steward_payload(**overrides), ADMIN)
    )


def create_source_system(certify: bool = True, **overrides) -> Dict[str, Any]:
    system = get_success_data(
        api_client.create_source_system(source_system_payload(**overrides), ADMIN)
    )
    if certify:
        system = get_success_data(
            api_client.certify_source_system(system["id"], ADMIN)
        )
    return system


def assign_steward(
    domain_id: str, steward_id: str, steward_role: str, **overrides
) -> Dict[str, Any]:
    """Create a steward assignment, reading the live domain version first."""
    payload = steward_assignment_payload(
        domain_id,
        steward_id,
        overrides.pop("expected_domain_version", domain_version(domain_id)),
        steward_role=steward_role,
        **overrides,
    )
    return get_success_data(api_client.create_steward_assignment(payload, ADMIN))


def register_source(
    domain_id: str, source_system_id: str, role: str = "AUTHORITATIVE", **overrides
) -> Dict[str, Any]:
    """Create a source registration, reading the live domain version first."""
    payload = source_registration_payload(
        domain_id,
        source_system_id,
        overrides.pop("expected_domain_version", domain_version(domain_id)),
        role=role,
        **overrides,
    )
    return get_success_data(api_client.create_source_registration(payload, ADMIN))


def create_quality_rule(
    domain_id: str, owner_steward_id: str, acting_headers: Dict[str, str], **overrides
) -> Dict[str, Any]:
    payload = quality_rule_payload(domain_id, owner_steward_id, **overrides)
    return get_success_data(api_client.create_quality_rule(payload, acting_headers))


# --------------------------------------------------------------------------
# Tier 2 / Tier 3: the whole standing-up sequence
# --------------------------------------------------------------------------

DEFAULT_SOURCES: List[Dict[str, Any]] = [
    {
        "code": "ERP",
        "name": "ERP Core",
        "trust_tier": 4,
        "role": "AUTHORITATIVE",
        "trust_rank": 1,
        "certify": True,
        "register": True,
    }
]

DEFAULT_RULES: List[Dict[str, Any]] = [
    {
        "rule_code": "QR1",
        "dimension": "COMPLETENESS",
        "weight_points": 40,
        "threshold_pct": 90.00,
        "severity": "HIGH",
        "owner": "steward",
    }
]


def setup_governed_domain(
    clock: Optional[str] = CLOCK,
    activate: bool = True,
    domain_overrides: Optional[Dict[str, Any]] = None,
    sources: Optional[List[Dict[str, Any]]] = None,
    rules: Optional[List[Dict[str, Any]]] = None,
    third_steward: bool = False,
    third_steward_certification: str = "JUNIOR",
) -> Dict[str, Any]:
    """Stand a governed domain up and return the working context.

    Returned keys:
      ``domain``            latest domain read
      ``owner``             the PRINCIPAL steward holding the data-owner seat
      ``steward``           the SENIOR steward holding the data-steward seat
      ``third``             a further steward (only when ``third_steward``)
      ``sources``           {source code: source system}
      ``registrations``     {source code: source registration}
      ``rules``             {rule code: quality rule}
      ``admin_headers``     governance office headers
      ``owner_headers``     data-owner headers bound to ``owner['id']``
      ``steward_headers``   data-steward headers bound to ``steward['id']``
    """
    if clock is not None:
        set_clock(clock)

    domain = create_domain(**(domain_overrides or {}))

    owner = create_steward(
        full_name=TEST_DEFAULTS["OWNER_NAME"],
        email=TEST_DEFAULTS["OWNER_EMAIL"],
        certification_level="PRINCIPAL",
    )
    steward = create_steward(
        full_name=TEST_DEFAULTS["STEWARD_NAME"],
        email=TEST_DEFAULTS["STEWARD_EMAIL"],
        certification_level="SENIOR",
    )
    third = None
    if third_steward:
        third = create_steward(
            full_name=TEST_DEFAULTS["THIRD_STEWARD_NAME"],
            email=TEST_DEFAULTS["THIRD_STEWARD_EMAIL"],
            certification_level=third_steward_certification,
        )

    assign_steward(domain["id"], owner["id"], "DATA_OWNER")
    assign_steward(domain["id"], steward["id"], "DATA_STEWARD")

    owner_headers = make_data_owner_headers(owner["id"])
    steward_headers = make_data_steward_headers(steward["id"])

    systems: Dict[str, Any] = {}
    registrations: Dict[str, Any] = {}
    for spec in (DEFAULT_SOURCES if sources is None else sources):
        spec = dict(spec)
        code = spec["code"]
        system = create_source_system(
            certify=spec.get("certify", True),
            code=code,
            name=spec.get("name", f"{code} System"),
            trust_tier=spec.get("trust_tier", 4),
        )
        systems[code] = system
        if spec.get("register", True):
            registrations[code] = register_source(
                domain["id"],
                system["id"],
                role=spec.get("role", "CONTRIBUTING"),
                trust_rank=spec.get("trust_rank", 1),
                effective_from=spec.get(
                    "effective_from", TEST_DEFAULTS["EFFECTIVE_FROM"]
                ),
            )

    quality_rules: Dict[str, Any] = {}
    for spec in (DEFAULT_RULES if rules is None else rules):
        spec = dict(spec)
        owner_key = spec.pop("owner", "steward")
        owner_steward_id = owner["id"] if owner_key == "owner" else steward["id"]
        rule = create_quality_rule(
            domain["id"], owner_steward_id, steward_headers, **spec
        )
        quality_rules[rule["rule_code"]] = rule

    if activate:
        domain = get_success_data(api_client.activate_domain(domain["id"], ADMIN))
    else:
        domain = read_domain(domain["id"])

    return {
        "domain": domain,
        "owner": owner,
        "steward": steward,
        "third": third,
        "sources": systems,
        "registrations": registrations,
        "rules": quality_rules,
        "admin_headers": ADMIN,
        "owner_headers": owner_headers,
        "steward_headers": steward_headers,
    }


def setup_draft_domain(**kwargs) -> Dict[str, Any]:
    """A domain that has not been activated yet."""
    kwargs.setdefault("activate", False)
    return setup_governed_domain(**kwargs)


def setup_multi_source_domain(**kwargs) -> Dict[str, Any]:
    """WMS holds the authoritative registration; ERP and CRM contribute."""
    kwargs.setdefault(
        "sources",
        [
            {
                "code": "WMS",
                "name": "Warehouse Master",
                "trust_tier": 3,
                "role": "AUTHORITATIVE",
                "trust_rank": 1,
            },
            {
                "code": "ERP",
                "name": "ERP Core",
                "trust_tier": 4,
                "role": "CONTRIBUTING",
                "trust_rank": 2,
            },
            {
                "code": "CRM",
                "name": "CRM Cloud",
                "trust_tier": 5,
                "role": "CONTRIBUTING",
                "trust_rank": 3,
            },
        ],
    )
    return setup_governed_domain(**kwargs)


def refresh_domain(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Re-read the context's domain, store it back on the context, return it."""
    ctx["domain"] = read_domain(ctx["domain"]["id"])
    return ctx["domain"]


# --------------------------------------------------------------------------
# Tier 3: master records, merges, findings
# --------------------------------------------------------------------------


def add_master_record(
    ctx: Dict[str, Any],
    source_code: str = "ERP",
    curate: bool = True,
    publish: bool = False,
    **overrides,
) -> Dict[str, Any]:
    """Ingest a candidate record and optionally curate then publish it."""
    payload = master_record_payload(
        ctx["domain"]["id"], ctx["sources"][source_code]["id"], **overrides
    )
    record = get_success_data(
        api_client.create_master_record(payload, ctx["steward_headers"])
    )
    if curate:
        record = get_success_data(
            api_client.curate_master_record(record["id"], ctx["steward_headers"])
        )
    if publish:
        record = get_success_data(
            api_client.publish_master_record(record["id"], ctx["steward_headers"])
        )
    return record


def add_merge_proposal(
    ctx: Dict[str, Any],
    survivor: Dict[str, Any],
    duplicate: Dict[str, Any],
    review: bool = True,
    **overrides,
) -> Dict[str, Any]:
    """Propose a duplicate resolution and optionally take it under review."""
    payload = merge_proposal_payload(survivor["id"], duplicate["id"], **overrides)
    proposal = get_success_data(
        api_client.create_merge_proposal(payload, ctx["steward_headers"])
    )
    if review:
        proposal = get_success_data(
            api_client.review_merge_proposal(proposal["id"], ctx["steward_headers"])
        )
    return proposal


def setup_domain_with_duplicate_records(
    ctx: Optional[Dict[str, Any]] = None,
    survivor_source: str = "ERP",
    duplicate_source: str = "CRM",
    survivor_overrides: Optional[Dict[str, Any]] = None,
    duplicate_overrides: Optional[Dict[str, Any]] = None,
    **setup_kwargs,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Two curated records of one domain, ready to be proposed as duplicates.

    Returns (context, survivor candidate, duplicate candidate).
    """
    if ctx is None:
        ctx = setup_multi_source_domain(**setup_kwargs)
    survivor_defaults = {
        "natural_key": "ERP-CUST-1001",
        "attributes": {"legal_name": "Acme Industrial", "tax_id": "TX-77"},
        "last_verified_at": "2026-07-01T00:00:00Z",
    }
    survivor_defaults.update(survivor_overrides or {})
    duplicate_defaults = {
        "natural_key": "CRM-CUST-9001",
        "attributes": {
            "legal_name": "Acme Industrial Inc",
            "tax_id": "TX-77",
            "billing_city": "Austin",
            "contact_email": "ops@acme.test",
        },
        "last_verified_at": "2026-08-01T00:00:00Z",
    }
    duplicate_defaults.update(duplicate_overrides or {})
    survivor = add_master_record(ctx, source_code=survivor_source, **survivor_defaults)
    duplicate = add_master_record(
        ctx, source_code=duplicate_source, **duplicate_defaults
    )
    return ctx, survivor, duplicate


def run_scorecard(
    ctx: Dict[str, Any],
    basis: str = "CERTIFIED",
    measurements: Optional[List[Dict[str, Any]]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Run the scorecard for the context's domain and return the run."""
    payload = {"basis": basis, "measurements": measurements or []}
    return get_success_data(
        api_client.create_scorecard_run(
            ctx["domain"]["id"], payload, headers or ctx["steward_headers"]
        )
    )


def list_findings(ctx: Dict[str, Any], **params) -> List[Dict[str, Any]]:
    response = api_client.list_quality_findings(ADMIN, params=params or None)
    return get_success_data(response)


def open_finding(
    ctx: Dict[str, Any],
    rule_code: str = "QR1",
    measured_pct: float = 50.00,
    basis: str = "CERTIFIED",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Breach one rule so a finding opens. Returns (run, finding)."""
    run = run_scorecard(
        ctx, basis=basis, measurements=[{"rule_code": rule_code, "measured_pct": measured_pct}]
    )
    rule = ctx["rules"][rule_code]
    findings = list_findings(
        ctx, scorecard_run_id=run["id"], quality_rule_id=rule["id"]
    )
    assert findings, (
        f"Setup expected a finding on rule {rule_code} from run {run['id']}"
    )
    return run, findings[0]


def setup_domain_with_open_critical_finding(
    measured_pct: float = 50.00, **setup_kwargs
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """A domain held at a restricted posture by one open critical finding.

    Returns (context, scorecard run, finding).
    """
    setup_kwargs.setdefault(
        "rules",
        [
            {
                "rule_code": "QR1",
                "dimension": "COMPLETENESS",
                "weight_points": 40,
                "threshold_pct": 90.00,
                "severity": "CRITICAL",
                "owner": "owner",
            }
        ],
    )
    ctx = setup_governed_domain(**setup_kwargs)
    run, finding = open_finding(ctx, "QR1", measured_pct)
    refresh_domain(ctx)
    return ctx, run, finding


# --------------------------------------------------------------------------
# Tier 3: consumers and change requests
# --------------------------------------------------------------------------


def add_consumer_subscription(
    ctx: Dict[str, Any],
    document_lineage: bool = False,
    lineage_path: Optional[List[str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """Register a downstream consumer, optionally documenting its lineage."""
    payload = consumer_subscription_payload(ctx["domain"]["id"], **overrides)
    subscription = get_success_data(
        api_client.create_consumer_subscription(payload, ADMIN)
    )
    if document_lineage:
        subscription = document_lineage_for(ctx, subscription, lineage_path)
    return subscription


def document_lineage_for(
    ctx: Dict[str, Any],
    subscription: Dict[str, Any],
    lineage_path: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Document a lineage path running from the authoritative source code
    through one transformation node to the subscription's reporting asset."""
    if lineage_path is None:
        authoritative = refresh_domain(ctx)["authoritative_source_code"]
        lineage_path = [
            authoritative,
            f"STG_{subscription['consumer_code']}",
            subscription["reporting_asset_key"],
        ]
    return get_success_data(
        api_client.document_consumer_lineage(
            subscription["id"], {"lineage_path": lineage_path}, ctx["steward_headers"]
        )
    )


def acknowledge_subscription(subscription: Dict[str, Any]) -> Dict[str, Any]:
    """Acknowledge the pending notification as the subscription's own consumer."""
    return get_success_data(
        api_client.acknowledge_consumer_subscription(
            subscription["id"], make_consumer_rep_headers(subscription["id"])
        )
    )


def add_change_request(
    ctx: Dict[str, Any],
    stage: str = "DRAFT",
    scheduled_apply_at: Optional[str] = None,
    review_note: str = "Reviewed and approved by the reference data board",
    **overrides,
) -> Dict[str, Any]:
    """Raise a change request and drive it to the requested stage.

    ``stage`` is one of DRAFT, SUBMITTED, UNDER_REVIEW, APPROVED or SCHEDULED.
    """
    payload = change_request_payload(ctx["domain"]["id"], **overrides)
    request = get_success_data(
        api_client.create_change_request(payload, ctx["steward_headers"])
    )
    if stage == "DRAFT":
        return request

    request = get_success_data(
        api_client.submit_change_request(request["id"], ctx["steward_headers"])
    )
    if stage == "SUBMITTED":
        return request

    request = get_success_data(
        api_client.review_change_request(request["id"], ctx["owner_headers"])
    )
    if stage == "UNDER_REVIEW":
        return request

    request = get_success_data(
        api_client.decide_change_request(
            request["id"],
            {"decision": "APPROVE", "review_note": review_note},
            ctx["owner_headers"],
        )
    )
    if stage == "APPROVED":
        return request

    if stage == "SCHEDULED":
        assert scheduled_apply_at, (
            "Setup requires scheduled_apply_at to reach the SCHEDULED stage"
        )
        return get_success_data(
            api_client.schedule_change_request(
                request["id"],
                {"scheduled_apply_at": scheduled_apply_at},
                ctx["owner_headers"],
            )
        )

    raise AssertionError(f"Unsupported change request stage: {stage}")


def setup_notified_scheduled_change(
    ctx: Optional[Dict[str, Any]] = None,
    scheduled_apply_at: str = "2026-08-16T00:00:00Z",
    acknowledge: bool = True,
    **setup_kwargs,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """A scheduled reference-value addition with its consumers notified.

    Registers a TIER1 consumer requiring ten days of notice and a TIER2
    consumer requiring three, raises a reference-value addition and drives it
    all the way to SCHEDULED, then optionally has the TIER1 consumer
    acknowledge the notification it received.

    Returns (context, change request, TIER1 subscription, TIER2 subscription).
    """
    if ctx is None:
        ctx = setup_governed_domain(**setup_kwargs)
    tier1 = add_consumer_subscription(ctx)
    tier2 = add_consumer_subscription(
        ctx,
        consumer_code="BI_CUSTOMER_SUMMARY",
        reporting_asset_key="RPT_CUST_SUMMARY",
        criticality="TIER2",
        required_lead_days=3,
    )
    request = add_change_request(
        ctx,
        stage="SCHEDULED",
        scheduled_apply_at=scheduled_apply_at,
        review_note="New segment code approved by the reference data board",
    )
    if acknowledge:
        tier1 = acknowledge_subscription(tier1)
    return ctx, request, tier1, tier2


def setup_domain_awaiting_data_steward(
    clock: Optional[str] = CLOCK,
) -> Dict[str, Any]:
    """A DRAFT domain whose only accountability assignment is the data owner's.

    Two further stewards are registered but left unassigned, so a test can
    build the whole DATA_STEWARD accountability timeline itself.

    Returned keys: ``domain``, ``owner``, ``steward``, ``third``,
    ``admin_headers``.
    """
    if clock is not None:
        set_clock(clock)

    domain = create_domain()
    owner = create_steward(
        full_name=TEST_DEFAULTS["OWNER_NAME"],
        email=TEST_DEFAULTS["OWNER_EMAIL"],
        certification_level="PRINCIPAL",
    )
    steward = create_steward(
        full_name=TEST_DEFAULTS["STEWARD_NAME"],
        email=TEST_DEFAULTS["STEWARD_EMAIL"],
        certification_level="SENIOR",
    )
    third = create_steward(
        full_name=TEST_DEFAULTS["THIRD_STEWARD_NAME"],
        email=TEST_DEFAULTS["THIRD_STEWARD_EMAIL"],
        certification_level="JUNIOR",
    )
    assign_steward(domain["id"], owner["id"], "DATA_OWNER")

    return {
        "domain": read_domain(domain["id"]),
        "owner": owner,
        "steward": steward,
        "third": third,
        "admin_headers": ADMIN,
        "owner_headers": make_data_owner_headers(owner["id"]),
    }


def setup_approved_structural_requests(
    ctx: Dict[str, Any], count: int = 2
) -> List[Dict[str, Any]]:
    """Raise ``count`` approved hierarchy-restructure requests on the domain."""
    titles = [
        ("Move NA sales hierarchy under global", "NA_SALES"),
        ("Split EMEA sales hierarchy", "EMEA_SALES"),
        ("Split APAC sales hierarchy", "APAC_SALES"),
        ("Split LATAM sales hierarchy", "LATAM_SALES"),
    ]
    requests = []
    for index in range(count):
        title, child = titles[index % len(titles)]
        requests.append(
            add_change_request(
                ctx,
                stage="APPROVED",
                change_type="HIERARCHY_RESTRUCTURE",
                title=title,
                proposed_values={"parent_node_key": "GLOBAL", "child_node_key": child},
                review_note=f"Hierarchy realignment {index + 1} approved for the window",
            )
        )
    return requests
