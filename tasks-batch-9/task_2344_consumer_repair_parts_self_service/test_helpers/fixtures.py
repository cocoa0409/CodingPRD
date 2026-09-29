"""Composite setup helpers.

The database is empty at the start of every test, so every precondition is built here
from scratch through the endpoints the PRD declares. Helpers are layered: single
creates, then state progressions, then whole-lifecycle shortcuts, then accumulation
and terminal-state builders.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import api_client
from .test_users import (
    ADMIN,
    COMPLIANCE,
    CUSTOMER,
    DOCS,
    SAFETY,
    SAFETY_ALT,
    make_repair_provider_tech_headers,
)


# --------------------------------------------------------------------------- #
# Tier 0 — the logical clock
# --------------------------------------------------------------------------- #
def move_clock(to_iso8601, headers=ADMIN):
    """Move the logical clock strictly forward and return the response payload."""
    response = api_client.set_clock(factories.clock_payload(to_iso8601), headers)
    return get_success_data(response)


# --------------------------------------------------------------------------- #
# Tier 1 — single-entity creates and one-step progressions
# --------------------------------------------------------------------------- #
def create_region(headers=ADMIN, **overrides):
    response = api_client.create_compliance_profile(
        factories.compliance_profile_payload(**overrides), headers
    )
    return get_success_data(response)


def create_model(headers=ADMIN, **overrides):
    response = api_client.create_product_model(
        factories.product_model_payload(**overrides), headers
    )
    return get_success_data(response)


def read_model(model_id, headers=ADMIN):
    return get_success_data(api_client.get_product_model(model_id, headers))


def model_version(model_id, headers=ADMIN):
    """The current version of a model, which the revision guard demands."""
    return read_model(model_id, headers)["version"]


def create_part(headers=ADMIN, **overrides):
    response = api_client.create_part_catalog_item(
        factories.part_catalog_item_payload(**overrides), headers
    )
    return get_success_data(response)


def read_part(part_id, headers=ADMIN):
    return get_success_data(api_client.get_part_catalog_item(part_id, headers))


def create_compatibility(part_id, model_id, headers=ADMIN, **overrides):
    response = api_client.create_part_compatibility(
        factories.part_compatibility_payload(part_id, model_id, **overrides), headers
    )
    return get_success_data(response)


def publish_part(part_id, headers=ADMIN):
    return get_success_data(api_client.publish_part_catalog_item(part_id, headers))


def restrict_part(part_id, headers=SAFETY, **overrides):
    response = api_client.restrict_part_catalog_item(
        part_id, factories.restriction_payload(**overrides), headers
    )
    return get_success_data(response)


def create_obligation(model_id, region_code, headers=COMPLIANCE, **overrides):
    response = api_client.create_compliance_obligation(
        factories.compliance_obligation_payload(model_id, region_code, **overrides), headers
    )
    return get_success_data(response)


def attest_obligation(obligation_id, headers=COMPLIANCE, **overrides):
    response = api_client.attest_obligation(
        obligation_id, factories.attestation_payload(**overrides), headers
    )
    return get_success_data(response)


def run_sweep(headers=COMPLIANCE, **overrides):
    response = api_client.run_compliance_sweep(
        factories.compliance_sweep_payload(**overrides), headers
    )
    return get_success_data(response)


def end_production(model_id, end_of_production_date, headers=ADMIN):
    response = api_client.end_production(
        model_id,
        factories.end_production_payload(end_of_production_date=end_of_production_date),
        headers,
    )
    return get_success_data(response)


def end_support(model_id, support_end_date, headers=ADMIN):
    response = api_client.end_support(
        model_id, factories.end_support_payload(support_end_date=support_end_date), headers
    )
    return get_success_data(response)


# --------------------------------------------------------------------------- #
# Tier 1 — a published catalog part with fitment on a model
# --------------------------------------------------------------------------- #
def create_published_part(
    model_id,
    part_overrides=None,
    compatibility_overrides=None,
    headers=ADMIN,
):
    """Register a part, give it fitment on the model, then publish it.

    Returns a dict with the created part and its compatibility row, both re-read after
    publication so their derived fields are current.
    """
    part = create_part(headers, **(part_overrides or {}))
    compatibility = create_compatibility(
        part["id"], model_id, headers, **(compatibility_overrides or {})
    )
    part = publish_part(part["id"], headers)
    return {"part": part, "compatibility": compatibility}


# --------------------------------------------------------------------------- #
# Tier 1 — the documentation revision cycle
# --------------------------------------------------------------------------- #
def create_draft_revision(model_id, author_headers=DOCS, **overrides):
    """Open a revision in draft, reading the model's current version for the guard."""
    payload = factories.manual_revision_payload(
        model_id, model_version(model_id), **overrides
    )
    return get_success_data(api_client.create_manual_revision(payload, author_headers))


def submit_revision(revision_id, headers=DOCS):
    return get_success_data(api_client.submit_manual_revision(revision_id, headers))


def review_revision(revision_id, decision="APPROVE", headers=SAFETY, **overrides):
    response = api_client.review_manual_revision(
        revision_id, factories.review_decision_payload(decision, **overrides), headers
    )
    return get_success_data(response)


def publish_revision(revision_id, headers=SAFETY, **overrides):
    response = api_client.publish_manual_revision(
        revision_id, headers, factories.publish_revision_payload(**overrides)
    )
    return get_success_data(response)


def create_published_revision(
    model_id,
    doc_type="DISASSEMBLY_GUIDE",
    covered_part_skus=None,
    safety_warning_count=3,
    effective_from=None,
    author_headers=DOCS,
    reviewer_headers=SAFETY,
):
    """Drive one revision from draft all the way to published.

    The reviewer identity must differ from the author identity, because the review
    decision is refused when the caller authored the revision.
    """
    revision = create_draft_revision(
        model_id,
        author_headers,
        doc_type=doc_type,
        covered_part_skus=list(covered_part_skus or []),
        safety_warning_count=safety_warning_count,
    )
    submit_revision(revision["id"], author_headers)
    review_revision(revision["id"], "APPROVE", reviewer_headers)
    publish_kwargs = {} if effective_from is None else {"effective_from": effective_from}
    return publish_revision(revision["id"], reviewer_headers, **publish_kwargs)


def publish_disassembly_guide(model_id, covered_part_skus, safety_warning_count=3, **kwargs):
    return create_published_revision(
        model_id,
        "DISASSEMBLY_GUIDE",
        covered_part_skus,
        safety_warning_count,
        **kwargs,
    )


def publish_calibration_procedure(model_id, covered_part_skus, safety_warning_count=2, **kwargs):
    return create_published_revision(
        model_id,
        "CALIBRATION_PROCEDURE",
        covered_part_skus,
        safety_warning_count,
        **kwargs,
    )


def publish_safety_sheet(model_id, covered_part_skus, safety_warning_count=2, **kwargs):
    return create_published_revision(
        model_id,
        "SAFETY_SHEET",
        covered_part_skus,
        safety_warning_count,
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# Tier 2 — eligibility and the order hierarchy
# --------------------------------------------------------------------------- #
def create_assessment(model_id, part_id, region_code, headers=CUSTOMER, **overrides):
    response = api_client.create_eligibility_assessment(
        factories.eligibility_assessment_payload(model_id, part_id, region_code, **overrides),
        headers,
    )
    return get_success_data(response)


def read_assessment(assessment_id, headers=ADMIN):
    return get_success_data(api_client.get_eligibility_assessment(assessment_id, headers))


def create_order(assessment_id, region_code, headers=CUSTOMER, **overrides):
    response = api_client.create_parts_order(
        factories.parts_order_payload(assessment_id, region_code, **overrides), headers
    )
    return get_success_data(response)


def read_order(order_id, headers=ADMIN):
    return get_success_data(api_client.get_parts_order(order_id, headers))


def order_version(order_id, headers=ADMIN):
    """The current version of an order, which the line-append guard demands."""
    return read_order(order_id, headers)["version"]


def append_line(order_id, part_id, quantity=1, headers=CUSTOMER, **overrides):
    """Append one line, re-reading the order version first as the guard requires."""
    payload = factories.order_line_payload(
        part_id, order_version(order_id, headers), quantity, **overrides
    )
    return get_success_data(api_client.append_order_line(order_id, payload, headers))


def list_lines(order_id, headers=ADMIN):
    response = api_client.list_lines_for_order(order_id, headers, params={"limit": 100})
    return get_success_data(response)


def request_disclosure(order_id, headers=CUSTOMER):
    return get_success_data(api_client.request_disclosure(order_id, headers))


def acknowledge_disclosure(order_id, headers=CUSTOMER, acknowledged_scope="FULL_SELF_REPAIR"):
    """Sign the disclosure, echoing the values the order and its assessment carry.

    The acknowledgment must repeat the order's computed warranty impact class and the
    liability warning version pinned on the assessment, so both are read back rather
    than assumed.
    """
    order = read_order(order_id, headers)
    assessment = read_assessment(order["assessment_id"], headers)
    payload = factories.acknowledgment_payload(
        order["warranty_impact_class"],
        assessment["liability_warning_version"],
        acknowledged_scope,
    )
    return get_success_data(api_client.create_acknowledgment(order_id, payload, headers))


def confirm_order(order_id, headers=CUSTOMER):
    return get_success_data(api_client.confirm_order(order_id, headers))


def deliver_order(order_id, headers=ADMIN, **overrides):
    return get_success_data(api_client.deliver_order(order_id, headers, overrides or {}))


def cancel_order(order_id, headers=CUSTOMER, **overrides):
    response = api_client.cancel_order(
        order_id, factories.cancellation_payload(**overrides), headers
    )
    return get_success_data(response)


def book_core_return(order_id, received_at, core_condition="INTACT", headers=ADMIN):
    response = api_client.book_core_return(
        order_id, factories.core_return_payload(received_at, core_condition), headers
    )
    return get_success_data(response)


def authenticate_line(order_id, line_id, pairing_token, headers=ADMIN):
    response = api_client.authenticate_line(
        order_id, line_id, factories.authenticate_payload(pairing_token), headers
    )
    return get_success_data(response)


def calibrate_line(order_id, line_id, measured_offset_ppm, headers=ADMIN):
    response = api_client.calibrate_line(
        order_id, line_id, factories.calibrate_payload(measured_offset_ppm), headers
    )
    return get_success_data(response)


# --------------------------------------------------------------------------- #
# Tier 3 — whole-lifecycle shortcuts
# --------------------------------------------------------------------------- #
def build_orderable_setup(
    region_overrides=None,
    model_overrides=None,
    part_overrides=None,
    compatibility_overrides=None,
    safety_warning_count=3,
):
    """A region, a model, one published part with fitment, and a published guide.

    The guide is authored after the part is published and lists that part's SKU, so
    the model's documentation posture settles at current and the guide carries no
    coverage gap.
    """
    region = create_region(**(region_overrides or {}))
    model = create_model(**(model_overrides or {}))
    published = create_published_part(
        model["id"], part_overrides, compatibility_overrides
    )
    guide = publish_disassembly_guide(
        model["id"], [published["part"]["sku"]], safety_warning_count
    )
    return {
        "region": region,
        "model": read_model(model["id"]),
        "part": read_part(published["part"]["id"]),
        "compatibility": published["compatibility"],
        "guide": guide,
    }


def add_published_part(setup, part_overrides=None, compatibility_overrides=None):
    """Add one more published part to an existing setup, refreshing the guide coverage.

    A newly published part that the current guide does not list drives the model's
    documentation posture to stale, so a fresh guide covering every published SKU is
    published afterwards.
    """
    published = create_published_part(
        setup["model"]["id"], part_overrides, compatibility_overrides
    )
    skus = [setup["part"]["sku"], published["part"]["sku"]]
    extra = [p["sku"] for p in setup.get("extra_parts", [])]
    guide = publish_disassembly_guide(
        setup["model"]["id"], skus + extra, setup["guide"]["safety_warning_count"]
    )
    setup.setdefault("extra_parts", []).append(published["part"])
    setup["guide"] = guide
    setup["model"] = read_model(setup["model"]["id"])
    return published


def build_draft_order(
    setup,
    quantity=1,
    buyer_headers=CUSTOMER,
    assessment_overrides=None,
    order_overrides=None,
    line_part_id=None,
):
    """An assessment plus an order in draft carrying one line."""
    assessment = create_assessment(
        setup["model"]["id"],
        setup["part"]["id"],
        setup["region"]["region_code"],
        buyer_headers,
        **(assessment_overrides or {}),
    )
    order = create_order(
        assessment["id"],
        setup["region"]["region_code"],
        buyer_headers,
        **(order_overrides or {}),
    )
    line = append_line(
        order["id"], line_part_id or setup["part"]["id"], quantity, buyer_headers
    )
    return {
        "assessment": assessment,
        "order": read_order(order["id"], buyer_headers),
        "line": line,
    }


def build_pending_disclosure_order(setup, quantity=1, buyer_headers=CUSTOMER, **kwargs):
    """A draft order advanced to pending disclosure, with its money frozen."""
    bundle = build_draft_order(setup, quantity, buyer_headers, **kwargs)
    bundle["order"] = request_disclosure(bundle["order"]["id"], buyer_headers)
    return bundle


def build_confirmed_order(
    setup,
    quantity=1,
    buyer_headers=CUSTOMER,
    acknowledged_scope="FULL_SELF_REPAIR",
    **kwargs,
):
    """An order carried through disclosure, acknowledgment and confirmation."""
    bundle = build_pending_disclosure_order(setup, quantity, buyer_headers, **kwargs)
    bundle["acknowledgment"] = acknowledge_disclosure(
        bundle["order"]["id"], buyer_headers, acknowledged_scope
    )
    bundle["order"] = confirm_order(bundle["order"]["id"], buyer_headers)
    return bundle


def build_delivered_order(
    setup,
    quantity=1,
    buyer_headers=CUSTOMER,
    acknowledged_scope="FULL_SELF_REPAIR",
    **kwargs,
):
    """A confirmed order marked delivered, which activates the per-line service steps."""
    bundle = build_confirmed_order(setup, quantity, buyer_headers, acknowledged_scope, **kwargs)
    bundle["order"] = deliver_order(bundle["order"]["id"])
    bundle["lines"] = list_lines(bundle["order"]["id"])
    return bundle


# --------------------------------------------------------------------------- #
# Tier 4 — accumulation and threshold targeting on the provider programme
# --------------------------------------------------------------------------- #
def create_provider(region_code, headers=ADMIN, **overrides):
    response = api_client.create_repair_provider(
        factories.repair_provider_payload(region_code, **overrides), headers
    )
    return get_success_data(response)


def read_provider(provider_id, headers=ADMIN):
    return get_success_data(api_client.get_repair_provider(provider_id, headers))


def begin_training(provider_id, training_credit_grant=8, headers=ADMIN):
    response = api_client.begin_provider_training(
        provider_id, factories.begin_training_payload(training_credit_grant), headers
    )
    return get_success_data(response)


def file_certification(provider_id, technician_user_id, headers=ADMIN, **overrides):
    response = api_client.create_training_certification(
        factories.training_certification_payload(
            provider_id, technician_user_id, **overrides
        ),
        headers,
    )
    return get_success_data(response)


def void_certification(certification_id, headers=ADMIN, **overrides):
    response = api_client.void_training_certification(
        certification_id, factories.void_certification_payload(**overrides), headers
    )
    return get_success_data(response)


def decide_authorization(provider_id, decision="AUTHORIZE", headers=ADMIN, **overrides):
    response = api_client.decide_provider_authorization(
        provider_id, factories.authorization_decision_payload(decision, **overrides), headers
    )
    return get_success_data(response)


def list_provider_certifications(provider_id, headers=ADMIN):
    response = api_client.list_provider_certifications(
        provider_id, headers, params={"limit": 100}
    )
    return get_success_data(response)


def build_provider_in_training(
    region_code,
    technician_count=4,
    training_credit_grant=8,
    provider_overrides=None,
):
    """A registered provider whose training has begun and whose credits are granted."""
    provider = create_provider(
        region_code, technician_count=technician_count, **(provider_overrides or {})
    )
    provider = begin_training(provider["id"], training_credit_grant)
    return provider


def build_authorized_provider(
    region_code,
    technician_user_ids,
    technician_count=4,
    training_credit_grant=8,
    provider_overrides=None,
    certification_overrides=None,
    granted_access_tier=None,
):
    """A provider carried to authorized status with enough certified technicians.

    One certification is filed per technician user id supplied, which is what the
    coverage requirement on the authorization decision reads.
    """
    provider = build_provider_in_training(
        region_code, technician_count, training_credit_grant, provider_overrides
    )
    certifications = []
    for index, technician_user_id in enumerate(technician_user_ids):
        overrides = dict(certification_overrides or {})
        overrides.setdefault("course_code", "CRS_GENERAL_REPAIR")
        certifications.append(
            file_certification(provider["id"], technician_user_id, ADMIN, **overrides)
        )
        del index
    decision_kwargs = {}
    if granted_access_tier is not None:
        decision_kwargs["granted_access_tier"] = granted_access_tier
    provider = decide_authorization(provider["id"], "AUTHORIZE", ADMIN, **decision_kwargs)
    return {"provider": provider, "certifications": certifications}


def build_provider_order_setup(
    setup,
    technician_user_id,
    technician_count=4,
    training_credit_grant=8,
    granted_access_tier=None,
):
    """An authorized provider in the setup's region plus the technician headers for it."""
    bundle = build_authorized_provider(
        setup["region"]["region_code"],
        [technician_user_id],
        technician_count=technician_count,
        training_credit_grant=training_credit_grant,
        granted_access_tier=granted_access_tier,
    )
    bundle["headers"] = make_repair_provider_tech_headers(technician_user_id)
    return bundle


def build_provider_confirmed_order(
    setup,
    provider_bundle,
    quantity=1,
    acknowledged_scope="PROVIDER_MANAGED",
    **kwargs,
):
    """A provider-channel order carried through to confirmation."""
    headers = provider_bundle["headers"]
    provider_id = provider_bundle["provider"]["id"]
    assessment_overrides = {
        "requester_class": "AUTHORIZED_PROVIDER",
        "provider_id": provider_id,
    }
    assessment_overrides.update(kwargs.pop("assessment_overrides", {}) or {})
    order_overrides = {"buyer_class": "AUTHORIZED_PROVIDER", "provider_id": provider_id}
    order_overrides.update(kwargs.pop("order_overrides", {}) or {})
    return build_confirmed_order(
        setup,
        quantity,
        headers,
        acknowledged_scope,
        assessment_overrides=assessment_overrides,
        order_overrides=order_overrides,
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# Tier 5 — finalization and terminal states
# --------------------------------------------------------------------------- #
def create_defective_return(order_line_id, quantity=1, headers=CUSTOMER, **overrides):
    response = api_client.create_defective_return(
        factories.defective_return_payload(order_line_id, quantity, **overrides), headers
    )
    return get_success_data(response)


def receive_defective_return(case_id, headers=ADMIN, **overrides):
    response = api_client.receive_defective_return(
        case_id, headers, factories.receive_defective_return_payload(**overrides)
    )
    return get_success_data(response)


def record_analysis(
    case_id,
    root_cause_code="MANUFACTURING_DEFECT",
    defect_confirmed=True,
    headers=None,
    **overrides,
):
    from .test_users import FAILURE_ENGINEER

    response = api_client.record_failure_analysis(
        case_id,
        factories.failure_analysis_payload(root_cause_code, defect_confirmed, **overrides),
        headers or FAILURE_ENGINEER,
    )
    return get_success_data(response)


def decide_credit(case_id, decision="ISSUE_CREDIT", headers=ADMIN, **overrides):
    response = api_client.decide_defective_credit(
        case_id, factories.credit_decision_payload(decision, **overrides), headers
    )
    return get_success_data(response)


def build_analysed_case(
    order_line_id,
    quantity=1,
    root_cause_code="MANUFACTURING_DEFECT",
    defect_confirmed=True,
    filer_headers=CUSTOMER,
):
    """A defective return case filed, booked in and analysed, ready for a credit decision."""
    case = create_defective_return(order_line_id, quantity, filer_headers)
    case = receive_defective_return(case["id"])
    case = record_analysis(case["id"], root_cause_code, defect_confirmed)
    return case


def build_second_reviewer_revision(model_id, covered_part_skus, safety_warning_count=3):
    """A published revision whose reviewer is the alternate safety reviewer identity."""
    return create_published_revision(
        model_id,
        "DISASSEMBLY_GUIDE",
        covered_part_skus,
        safety_warning_count,
        reviewer_headers=SAFETY_ALT,
    )
