"""Composite setup helpers.

Every helper here is a pure API client: it drives the same public endpoints a
real operator would, from a cold server, and returns the decoded `data` payloads
so tests can assert against them.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import validate_paginated, validate_success

from . import factories as f
from .api_client import ApiClient
from .test_users import (
    ADMIN_HEADERS,
    COORDINATOR_HEADERS,
    MANAGER_HEADERS,
    OFFICER_HEADERS,
    make_laboratory_user_headers,
    make_supplier_user_headers,
)

Json = Dict[str, Any]


# ---------------------------------------------------------------------------
# Tier 1 primitives: one endpoint call each, success asserted
# ---------------------------------------------------------------------------


def set_clock(api: ApiClient, to_iso8601: str) -> Json:
    """Move the server-controlled logical clock."""
    return validate_success(api.set_clock(to_iso8601, headers=ADMIN_HEADERS), 200)


def create_rule(api: ApiClient, **overrides: Any) -> Json:
    return validate_success(
        api.create_rule(f.rule_payload(**overrides), headers=ADMIN_HEADERS), 201
    )


def create_category(api: ApiClient, **overrides: Any) -> Json:
    return validate_success(
        api.create_category(f.category_payload(**overrides), headers=ADMIN_HEADERS), 201
    )


def map_rule(api: ApiClient, category_id: str, rule_id: str, **overrides: Any) -> Json:
    return validate_success(
        api.create_mapping(
            f.mapping_payload(category_id, rule_id, **overrides), headers=ADMIN_HEADERS
        ),
        201,
    )


def create_supplier(api: ApiClient, **overrides: Any) -> Json:
    return validate_success(
        api.create_supplier(f.supplier_payload(**overrides), headers=ADMIN_HEADERS), 201
    )


def create_laboratory(api: ApiClient, **overrides: Any) -> Json:
    return validate_success(
        api.create_laboratory(f.laboratory_payload(**overrides), headers=ADMIN_HEADERS),
        201,
    )


def attest(api: ApiClient, laboratory_id: str, valid_through: str) -> Json:
    """Record the standing undue-influence prevention attestation."""
    return validate_success(
        api.record_attestation(
            laboratory_id,
            {"attestation_valid_through": valid_through},
            headers=ADMIN_HEADERS,
        ),
        200,
    )


def set_lab_state(api: ApiClient, laboratory_id: str, operational_state: str) -> Json:
    return validate_success(
        api.set_laboratory_operational_state(
            laboratory_id, {"operational_state": operational_state}, headers=ADMIN_HEADERS
        ),
        200,
    )


def accredit(api: ApiClient, laboratory_id: str, rule_id: str, **overrides: Any) -> Json:
    return validate_success(
        api.create_accreditation(
            laboratory_id, f.accreditation_payload(rule_id, **overrides), headers=ADMIN_HEADERS
        ),
        201,
    )


def suspend_accreditation(
    api: ApiClient, accreditation_id: str, suspension_reason: str
) -> Json:
    return validate_success(
        api.suspend_accreditation(
            accreditation_id,
            {"suspension_reason": suspension_reason},
            headers=ADMIN_HEADERS,
        ),
        200,
    )


def create_product(api: ApiClient, category_id: str, **overrides: Any) -> Json:
    return validate_success(
        api.create_product(f.product_payload(category_id, **overrides), headers=ADMIN_HEADERS),
        201,
    )


def add_part(api: ApiClient, product_id: str, supplier_id: str, **overrides: Any) -> Json:
    return validate_success(
        api.create_component_part(
            product_id, f.component_part_payload(supplier_id, **overrides), headers=ADMIN_HEADERS
        ),
        201,
    )


def submit_for_certification(api: ApiClient, product_id: str, evidence_path: str) -> Json:
    return validate_success(
        api.submit_for_certification(
            product_id, {"evidence_path": evidence_path}, headers=COORDINATOR_HEADERS
        ),
        200,
    )


def create_plan(api: ApiClient, product_id: str, **overrides: Any) -> Json:
    return validate_success(
        api.create_sampling_plan(
            product_id, f.sampling_plan_payload(**overrides), headers=COORDINATOR_HEADERS
        ),
        201,
    )


def activate_plan(api: ApiClient, plan_id: str) -> Json:
    return validate_success(
        api.activate_sampling_plan(plan_id, headers=COORDINATOR_HEADERS), 200
    )


def periodic_review(api: ApiClient, plan_id: str) -> Json:
    return validate_success(api.periodic_review(plan_id, headers=COORDINATOR_HEADERS), 200)


def book_order(
    api: ApiClient,
    product_id: str,
    plan_id: str,
    laboratory_id: str,
    rule_id: str,
    **overrides: Any,
) -> Json:
    return validate_success(
        api.create_test_order(
            f.test_order_payload(product_id, plan_id, laboratory_id, rule_id, **overrides),
            headers=COORDINATOR_HEADERS,
        ),
        201,
    )


def start_order(api: ApiClient, order_id: str, laboratory_id: str) -> Json:
    return validate_success(
        api.start_testing(order_id, headers=make_laboratory_user_headers(laboratory_id)), 200
    )


def report(api: ApiClient, order_id: str, laboratory_id: str, measured_value: float) -> Json:
    return validate_success(
        api.report_result(
            order_id,
            {"measured_value": measured_value},
            headers=make_laboratory_user_headers(laboratory_id),
        ),
        200,
    )


def run_order_to_pass(
    api: ApiClient,
    product_id: str,
    plan_id: str,
    laboratory_id: str,
    rule_id: str,
    measured_value: float = 10,
    **overrides: Any,
) -> Json:
    """Book, take into testing and report a passing measurement in one step."""
    order = book_order(api, product_id, plan_id, laboratory_id, rule_id, **overrides)
    start_order(api, order["id"], laboratory_id)
    return report(api, order["id"], laboratory_id, measured_value)


def submit_part_certificate(
    api: ApiClient,
    part_id: str,
    supplier_id: str,
    laboratory_id: str,
    rule_id: str,
    **overrides: Any,
) -> Json:
    return validate_success(
        api.submit_part_certificate(
            part_id,
            f.part_certificate_payload(laboratory_id, rule_id, **overrides),
            headers=make_supplier_user_headers(supplier_id),
        ),
        201,
    )


def record_reliance(
    api: ApiClient,
    certificate_id: str,
    decision: str = "RELY",
    documentation_ref: str = "RELIANCE-PKG-001",
    headers: Optional[Dict[str, str]] = None,
) -> Json:
    return validate_success(
        api.record_reliance_documentation(
            certificate_id,
            {
                "reliance_decision": decision,
                "reliance_documentation_ref": documentation_ref,
            },
            headers=headers or OFFICER_HEADERS,
        ),
        200,
    )


def draft_certificate(
    api: ApiClient, product_id: str, expected_product_version: int, **overrides: Any
) -> Json:
    return validate_success(
        api.draft_certificate(
            product_id,
            f.certificate_payload(expected_product_version, **overrides),
            headers=OFFICER_HEADERS,
        ),
        201,
    )


def issue_certificate(
    api: ApiClient, certificate_id: str, headers: Optional[Dict[str, str]] = None
) -> Json:
    return validate_success(
        api.issue_certificate(certificate_id, headers=headers or OFFICER_HEADERS), 200
    )


def void_certificate(api: ApiClient, certificate_id: str) -> Json:
    return validate_success(
        api.void_certificate(certificate_id, headers=OFFICER_HEADERS), 200
    )


def furnish_certificate(api: ApiClient, certificate_id: str) -> Json:
    return validate_success(
        api.furnish_certificate(certificate_id, headers=MANAGER_HEADERS), 200
    )


def recall_accompaniment(api: ApiClient, certificate_id: str) -> Json:
    return validate_success(
        api.recall_accompaniment(certificate_id, headers=MANAGER_HEADERS), 200
    )


def create_batch(api: ApiClient, product_id: str, certificate_id: str, **overrides: Any) -> Json:
    return validate_success(
        api.create_production_batch(
            product_id, f.batch_payload(certificate_id, **overrides), headers=MANAGER_HEADERS
        ),
        201,
    )


def release_batch(api: ApiClient, batch_id: str) -> Json:
    return validate_success(api.release_batch(batch_id, headers=MANAGER_HEADERS), 200)


def rescind_release(api: ApiClient, batch_id: str) -> Json:
    return validate_success(api.rescind_release(batch_id, headers=MANAGER_HEADERS), 200)


def record_material_change(api: ApiClient, product_id: str, **overrides: Any) -> Json:
    return validate_success(
        api.record_material_change(
            f.material_change_payload(product_id, **overrides), headers=ADMIN_HEADERS
        ),
        201,
    )


def issue_stop_distribution(
    api: ApiClient, case_id: str, scope_variant: str = "BATCH_SCOPED"
) -> Json:
    return validate_success(
        api.issue_stop_distribution(
            case_id, {"scope_variant": scope_variant}, headers=MANAGER_HEADERS
        ),
        200,
    )


def order_retest(
    api: ApiClient, case_id: str, plan_id: str, laboratory_id: str, **overrides: Any
) -> Json:
    return validate_success(
        api.order_retest(
            case_id, f.retest_payload(plan_id, laboratory_id, **overrides), headers=COORDINATOR_HEADERS
        ),
        200,
    )


def file_corrective_action(
    api: ApiClient, case_id: str, expected_case_version: int, ref: str = "CAPA-001"
) -> Json:
    return validate_success(
        api.file_corrective_action(
            case_id,
            {"expected_case_version": expected_case_version, "corrective_action_ref": ref},
            headers=OFFICER_HEADERS,
        ),
        200,
    )


def close_case(api: ApiClient, case_id: str, headers: Optional[Dict[str, str]] = None) -> Json:
    return validate_success(
        api.close_case(case_id, headers=headers or OFFICER_HEADERS), 200
    )


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------


def get_product(api: ApiClient, product_id: str) -> Json:
    return validate_success(api.get_product(product_id, headers=ADMIN_HEADERS), 200)


def get_summary(api: ApiClient, product_id: str) -> Json:
    return validate_success(
        api.get_compliance_summary(product_id, headers=ADMIN_HEADERS), 200
    )


def get_plan(api: ApiClient, plan_id: str) -> Json:
    return validate_success(api.get_sampling_plan(plan_id, headers=ADMIN_HEADERS), 200)


def get_order(api: ApiClient, order_id: str) -> Json:
    return validate_success(api.get_test_order(order_id, headers=ADMIN_HEADERS), 200)


def get_laboratory(api: ApiClient, laboratory_id: str) -> Json:
    return validate_success(api.get_laboratory(laboratory_id, headers=ADMIN_HEADERS), 200)


def get_supplier(api: ApiClient, supplier_id: str) -> Json:
    return validate_success(api.get_supplier(supplier_id, headers=ADMIN_HEADERS), 200)


def get_part(api: ApiClient, part_id: str) -> Json:
    return validate_success(api.get_component_part(part_id, headers=ADMIN_HEADERS), 200)


def get_part_certificate(api: ApiClient, certificate_id: str) -> Json:
    return validate_success(
        api.get_part_certificate(certificate_id, headers=ADMIN_HEADERS), 200
    )


def get_certificate(api: ApiClient, certificate_id: str) -> Json:
    return validate_success(api.get_certificate(certificate_id, headers=OFFICER_HEADERS), 200)


def get_batch(api: ApiClient, batch_id: str) -> Json:
    return validate_success(
        api.get_production_batch(batch_id, headers=MANAGER_HEADERS), 200
    )


def get_case(api: ApiClient, case_id: str) -> Json:
    return validate_success(api.get_case(case_id, headers=OFFICER_HEADERS), 200)


def list_cases_for_product(api: ApiClient, product_id: str) -> List[Json]:
    rows, _meta = validate_paginated(
        api.list_cases({"product_id": product_id}, headers=OFFICER_HEADERS)
    )
    return rows


def sole_case_for_product(api: ApiClient, product_id: str) -> Json:
    rows = list_cases_for_product(api, product_id)
    assert len(rows) == 1, f"expected exactly one noncompliance case, found {len(rows)}"
    return rows[0]


def list_orders_for_product(api: ApiClient, product_id: str, **filters: Any) -> List[Json]:
    params: Dict[str, Any] = {"product_id": product_id}
    params.update(filters)
    rows, _meta = validate_paginated(
        api.list_test_orders(params, headers=COORDINATOR_HEADERS)
    )
    return rows


def list_batches_for_product(api: ApiClient, product_id: str) -> List[Json]:
    rows, _meta = validate_paginated(
        api.list_production_batches({"product_id": product_id}, headers=MANAGER_HEADERS)
    )
    return rows


# ---------------------------------------------------------------------------
# Tier 2 composites: the entity hierarchy
# ---------------------------------------------------------------------------


def regulatory_env(
    api: ApiClient,
    rule_specs: Optional[List[Json]] = None,
    category: Optional[Json] = None,
) -> Json:
    """A category plus one active mapping per rule.

    Each entry of `rule_specs` is a set of rule field overrides; the optional
    keys `applicability_condition` and `effective_from` belong to the mapping
    rather than to the rule.
    """
    specs = rule_specs if rule_specs is not None else [{}]
    cat = create_category(api, **(category or {}))
    rules: List[Json] = []
    mappings: List[Json] = []
    for raw in specs:
        spec = dict(raw)
        condition = spec.pop("applicability_condition", "ALWAYS")
        effective_from = spec.pop("effective_from", "2026-01-01T00:00:00Z")
        rule = create_rule(api, **spec)
        rules.append(rule)
        mappings.append(
            map_rule(
                api,
                cat["id"],
                rule["id"],
                applicability_condition=condition,
                effective_from=effective_from,
            )
        )
    return {"category": cat, "rules": rules, "mappings": mappings}


def party_env(
    api: ApiClient,
    rules: List[Json],
    laboratory: Optional[Json] = None,
    supplier: Optional[Json] = None,
    attestation_valid_through: str = "2027-12-31T00:00:00Z",
    accreditation_overrides: Optional[List[Json]] = None,
) -> Json:
    """An attested laboratory accredited for every rule's method, plus a supplier."""
    lab = create_laboratory(api, **(laboratory or {}))
    attest(api, lab["id"], attestation_valid_through)
    accreditations: List[Json] = []
    for index, rule in enumerate(rules):
        extra: Json = {}
        if accreditation_overrides is not None and index < len(accreditation_overrides):
            extra = dict(accreditation_overrides[index])
        accreditations.append(accredit(api, lab["id"], rule["id"], **extra))
    sup = create_supplier(api, **(supplier or {}))
    return {
        "laboratory": get_laboratory(api, lab["id"]),
        "accreditations": accreditations,
        "supplier": sup,
    }


def scoped_product_env(
    api: ApiClient,
    evidence_path: str = "FULL_PRODUCT_TEST",
    rule_specs: Optional[List[Json]] = None,
    category: Optional[Json] = None,
    product: Optional[Json] = None,
    part_specs: Optional[List[Json]] = None,
    laboratory: Optional[Json] = None,
    supplier: Optional[Json] = None,
    attestation_valid_through: str = "2027-12-31T00:00:00Z",
    accreditation_overrides: Optional[List[Json]] = None,
    submit: bool = True,
) -> Json:
    """Library, parties, a registered product with its bill of materials.

    With `submit` left true the product is scoped onto `evidence_path`, which
    also forks it onto the matching evidence branch.
    """
    env = regulatory_env(api, rule_specs, category)
    env.update(
        party_env(
            api,
            env["rules"],
            laboratory,
            supplier,
            attestation_valid_through,
            accreditation_overrides,
        )
    )
    prod = create_product(api, env["category"]["id"], **(product or {}))
    specs = part_specs if part_specs is not None else [{}]
    parts: List[Json] = []
    for raw in specs:
        spec = dict(raw)
        supplier_id = spec.pop("supplier_id", env["supplier"]["id"])
        parts.append(add_part(api, prod["id"], supplier_id, **spec))
    if submit:
        prod = submit_for_certification(api, prod["id"], evidence_path)
    env.update({"product": prod, "parts": parts, "evidence_path": evidence_path})
    return env


# ---------------------------------------------------------------------------
# Tier 3 composites: full-lifecycle shortcuts
# ---------------------------------------------------------------------------


def booking_env(
    api: ApiClient,
    plan_overrides: Optional[Json] = None,
    evidence_path: str = "FULL_PRODUCT_TEST",
    **kwargs: Any,
) -> Json:
    """A scoped product with one activated sampling plan, ready to book testing."""
    env = scoped_product_env(api, evidence_path=evidence_path, **kwargs)
    plan = create_plan(api, env["product"]["id"], **(plan_overrides or {}))
    env["plan"] = activate_plan(api, plan["id"])
    env["product"] = get_product(api, env["product"]["id"])
    return env


def evidence_complete_env(
    api: ApiClient,
    plan_overrides: Optional[Json] = None,
    order_overrides: Optional[Json] = None,
    measured_value: float = 10,
    **kwargs: Any,
) -> Json:
    """A full-product-test product carried to EVIDENCE_COMPLETE by passing orders."""
    env = booking_env(api, plan_overrides=plan_overrides, **kwargs)
    orders: List[Json] = []
    for rule in env["rules"]:
        orders.append(
            run_order_to_pass(
                api,
                env["product"]["id"],
                env["plan"]["id"],
                env["laboratory"]["id"],
                rule["id"],
                measured_value,
                **(order_overrides or {}),
            )
        )
    env["orders"] = orders
    env["plan"] = get_plan(api, env["plan"]["id"])
    env["product"] = get_product(api, env["product"]["id"])
    return env


def reliance_env(
    api: ApiClient,
    rely: bool = True,
    **kwargs: Any,
) -> Json:
    """A component-reliance product with a supplier certificate per part and rule."""
    kwargs.setdefault("supplier", {"reliance_agreement_state": "ON_FILE"})
    env = scoped_product_env(api, evidence_path="COMPONENT_RELIANCE", **kwargs)
    certificates: List[Json] = []
    for part in env["parts"]:
        for rule in env["rules"]:
            certificate = submit_part_certificate(
                api,
                part["id"],
                env["supplier"]["id"],
                env["laboratory"]["id"],
                rule["id"],
            )
            if rely:
                certificate = record_reliance(api, certificate["id"])
            certificates.append(certificate)
    env["part_certificates"] = certificates
    env["product"] = get_product(api, env["product"]["id"])
    return env


def certified_env(
    api: ApiClient,
    certificate_overrides: Optional[Json] = None,
    **kwargs: Any,
) -> Json:
    """A product carried all the way to CERTIFIED with an ISSUED certificate."""
    env = evidence_complete_env(api, **kwargs)
    current = get_product(api, env["product"]["id"])
    certificate = draft_certificate(
        api, current["id"], current["version"], **(certificate_overrides or {})
    )
    env["certificate"] = issue_certificate(api, certificate["id"])
    env["product"] = get_product(api, env["product"]["id"])
    return env


def distributed_env(
    api: ApiClient,
    batch_specs: Optional[List[Json]] = None,
    release: bool = True,
    **kwargs: Any,
) -> Json:
    """A certified product whose furnished certificate carries production batches."""
    env = certified_env(api, **kwargs)
    furnish_certificate(api, env["certificate"]["id"])
    specs = batch_specs if batch_specs is not None else [{}]
    batches: List[Json] = []
    for spec in specs:
        batch = create_batch(api, env["product"]["id"], env["certificate"]["id"], **spec)
        if release:
            batch = release_batch(api, batch["id"])
        batches.append(batch)
    env["batches"] = batches
    env["certificate"] = get_certificate(api, env["certificate"]["id"])
    env["product"] = get_product(api, env["product"]["id"])
    return env


# ---------------------------------------------------------------------------
# Tier 4/5 composites: noncompliance response and terminal states
# ---------------------------------------------------------------------------


def fail_an_order(
    api: ApiClient,
    env: Json,
    rule_index: int = 0,
    measured_value: float = 250,
    **order_overrides: Any,
) -> Json:
    """Book, start and fail one order, firing the stop-distribution cascade."""
    rule = env["rules"][rule_index]
    order = book_order(
        api,
        env["product"]["id"],
        env["plan"]["id"],
        env["laboratory"]["id"],
        rule["id"],
        **order_overrides,
    )
    start_order(api, order["id"], env["laboratory"]["id"])
    return report(api, order["id"], env["laboratory"]["id"], measured_value)


def failed_case_env(
    api: ApiClient,
    failing_measured_value: float = 250,
    failing_order_overrides: Optional[Json] = None,
    **kwargs: Any,
) -> Json:
    """A distributed product whose fresh failing report opened a noncompliance case."""
    env = distributed_env(api, **kwargs)
    env["failing_order"] = fail_an_order(
        api,
        env,
        measured_value=failing_measured_value,
        **(failing_order_overrides or {}),
    )
    env["case"] = sole_case_for_product(api, env["product"]["id"])
    env["product"] = get_product(api, env["product"]["id"])
    return env


def stopped_case_env(
    api: ApiClient, scope_variant: str = "BATCH_SCOPED", **kwargs: Any
) -> Json:
    """A noncompliance case that has already issued its stop-distribution instruction.

    The batch is left on hold rather than released, because a case needs a batch in
    `HELD` or `RELEASED` for the stop-distribution instruction to have anything to act
    on, and the failing report already stops every released batch.
    """
    kwargs.setdefault("release", False)
    env = failed_case_env(api, **kwargs)
    env["case"] = issue_stop_distribution(api, env["case"]["id"], scope_variant)
    env["product"] = get_product(api, env["product"]["id"])
    return env


def retest_case_env(
    api: ApiClient,
    failed_rounds: int = 0,
    retest_overrides: Optional[Json] = None,
    **kwargs: Any,
) -> Json:
    """A case with one live retest round, after `failed_rounds` earlier failures."""
    env = stopped_case_env(api, **kwargs)
    orders: List[Json] = []
    for _ in range(failed_rounds + 1):
        env["case"] = order_retest(
            api,
            env["case"]["id"],
            env["plan"]["id"],
            env["laboratory"]["id"],
            **(retest_overrides or {}),
        )
        order_id = env["case"]["active_retest_order_id"]
        orders.append(order_id)
        if len(orders) <= failed_rounds:
            start_order(api, order_id, env["laboratory"]["id"])
            report(api, order_id, env["laboratory"]["id"], 250)
            env["case"] = get_case(api, env["case"]["id"])
    env["retest_order_ids"] = orders
    env["product"] = get_product(api, env["product"]["id"])
    return env


def corrective_action_env(api: ApiClient, **kwargs: Any) -> Json:
    """A case whose retest passed and whose corrective action plan is on file."""
    env = retest_case_env(api, **kwargs)
    active = env["case"]["active_retest_order_id"]
    start_order(api, active, env["laboratory"]["id"])
    report(api, active, env["laboratory"]["id"], 10)
    case = get_case(api, env["case"]["id"])
    env["case"] = file_corrective_action(api, case["id"], case["version"])
    env["product"] = get_product(api, env["product"]["id"])
    return env
