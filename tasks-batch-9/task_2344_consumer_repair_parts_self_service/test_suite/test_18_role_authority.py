"""Who may do what: the exclusive write sets of the four operator roles, the shared
buyer flow, the identity-scoped review guard that no role grant can satisfy, and the
three analytic reads that are narrower than the catalogue they sit beside.
"""
from test_helpers import (
    ADMIN,
    COMPLIANCE,
    CUSTOMER,
    DOCS,
    FAILURE_ENGINEER,
    SAFETY,
    SAFETY_ALT,
    TECH,
    api_client,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

_UNKNOWN_ORDER = "ffffffff-ffff-ffff-ffff-ffffffffffff"
_UNKNOWN_LINE = "ffffffff-ffff-ffff-ffff-eeeeeeeeeeee"
_UNKNOWN_CASE = "aaaaaaaa-1111-aaaa-1111-aaaaaaaaaaaa"
_UNKNOWN_PART = "dddddddd-dddd-dddd-dddd-dddddddddddd"
_UNKNOWN_MODEL = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
_UNKNOWN_ASSESSMENT = "aaaaaaaa-3333-aaaa-3333-aaaaaaaaaaaa"


def _count(response):
    _, meta = validate_paginated(response)
    return meta["total_count"]


def test_the_admins_exclusive_writes_are_denied_to_every_other_role_before_any_lookup():
    """PRD §2.1: "A request whose role is one of the seven but is not among the roles the
    target endpoint authorises is rejected with `ERR_FORBIDDEN_ROLE` (403)."
    PRD §2.1: "A `ProgramAdmin` alone may register product models and drive both lifecycle
    actions, create and publish catalog items, register compatibility rows, deliver an
    order, book in a core return, register providers and start their training, void a
    certification, and book in a defective unit."
    PRD §2.9: "Checks are evaluated in one global order, and the first check whose
    condition holds returns immediately — no later check is evaluated, so the earlier code
    always masks the later one."
    PRD §3.1: "A freshly registered model starts with `support_state` at
    `ACTIVE_PRODUCTION` — or directly at `LEGACY_SUPPORT` when an `end_of_production_date`
    was supplied in the same request — with `support_end_date` null,
    `documentation_posture` at `MISSING`, `compliance_posture` at `OPEN`,
    `open_obligation_count` at zero, and both `published_disassembly_revision_number` and
    `published_safety_sheet_revision_number` null."

    Design: Corner/rbac/program_admin_catalog_and_lifecycle_writes_are_forbidden_to_every_other_role
    """
    model_payload = factories.product_model_payload(
        model_code="CRX-R1",
        product_family="CRX",
        market_release_date="2024-01-01T00:00:00Z",
        repairability_tier="TIER_B_GUIDED",
    )

    denials = (
        ("model registration", api_client.create_product_model(model_payload, SAFETY)),
        (
            "catalog registration",
            api_client.create_part_catalog_item(
                factories.part_catalog_item_payload(sku="SKU-R1-A"), DOCS
            ),
        ),
        (
            "fitment registration",
            api_client.create_part_compatibility(
                factories.part_compatibility_payload(
                    _UNKNOWN_PART,
                    _UNKNOWN_MODEL,
                    effective_from="2024-02-01T00:00:00Z",
                    install_minutes=10,
                ),
                COMPLIANCE,
            ),
        ),
        ("delivery", api_client.deliver_order(_UNKNOWN_ORDER, CUSTOMER)),
        (
            "core receipt",
            api_client.book_core_return(
                _UNKNOWN_ORDER,
                factories.core_return_payload("2026-08-01T00:00:00Z"),
                TECH,
            ),
        ),
        (
            "provider registration",
            api_client.create_repair_provider(
                factories.repair_provider_payload(
                    "US-CA",
                    legal_name="Unauthorised Applicant",
                    requested_access_tier="TIER_3_STANDARD",
                ),
                TECH,
            ),
        ),
        (
            "defective receipt",
            api_client.receive_defective_return(_UNKNOWN_CASE, FAILURE_ENGINEER),
        ),
    )
    for label, response in denials:
        validate_error(response, "ERR_FORBIDDEN_ROLE", 403)
        assert response.status_code == 403, (
            f"{label}: the role gate answers before anything else, got "
            f"{response.status_code}"
        )

    registered = validate_success(
        api_client.create_product_model(model_payload, ADMIN), 201
    )
    assert registered["support_state"] == "ACTIVE_PRODUCTION", (
        f"the same body from the one authorised role is accepted, got "
        f"{registered['support_state']}"
    )
    assert registered["compliance_posture"] == "OPEN", registered["compliance_posture"]

    assert _count(api_client.list_part_catalog_items(ADMIN, params={"limit": 50})) == 0, (
        "the refused catalog registration stored nothing"
    )
    assert (
        _count(api_client.list_part_compatibilities(ADMIN, params={"limit": 50})) == 0
    ), "the refused fitment registration stored nothing"
    assert _count(api_client.list_repair_providers(ADMIN, params={"limit": 50})) == 0, (
        "the refused provider registration stored nothing"
    )


def test_only_the_safety_reviewer_may_restrict_a_part_or_decide_and_publish_a_revision():
    """PRD §2.1: "A `SafetyReviewer` alone may restrict a published part — it is the only
    role that can raise a part's safety class and fire the four-hop safety cascade — and
    alone may render a review decision on a manual revision or publish one."
    PRD §2.1: "A `DocumentationEngineer` authors and submits revisions but can neither
    approve nor publish them, and cannot restrict a part."
    PRD §3.4: "An approval moves `IN_REVIEW` to `APPROVED` and stores
    `reviewed_by_user_id`, and carries three guards of its own: the caller's `X-User-ID`
    must differ from `authored_by_user_id`, or the decision is refused with
    `ERR_SELF_REVIEW_FORBIDDEN`; the parent model's `support_state` must not be
    `SUPPORT_ENDED`, or the approval is refused with `ERR_INVALID_STATE_TRANSITION`; and
    for a `DISASSEMBLY_GUIDE` the `coverage_gap_sku_count` must be exactly zero, or the
    approval is refused with `ERR_REVISION_COVERAGE_GAP`, because a guide that omits a
    published, in-window part of the model is not a complete guide."
    PRD §3.3: "The first hop sets the part's `status` to `RESTRICTED`, overwrites its
    `safety_class` from the body, and stores the reason."

    Design: Corner/rbac/safety_reviewer_alone_may_restrict_a_part_or_decide_a_review_and_others_are_rejected
    """
    model = fixtures.create_model(
        model_code="CRX-R2",
        product_family="CRX",
        market_release_date="2024-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )
    part = fixtures.create_part(sku="SKU-R2-A", list_price_cents=1000)
    fixtures.create_compatibility(
        part["id"],
        model["id"],
        effective_from="2024-02-01T00:00:00Z",
        install_minutes=20,
    )
    fixtures.publish_part(part["id"])

    revision = fixtures.create_draft_revision(
        model["id"],
        DOCS,
        doc_type="DISASSEMBLY_GUIDE",
        covered_part_skus=["SKU-R2-A"],
        safety_warning_count=2,
    )
    submitted = fixtures.submit_revision(revision["id"], DOCS)
    assert submitted["status"] == "IN_REVIEW", (
        f"the documentation engineer may author and submit, got {submitted['status']}"
    )
    assert submitted["authored_by_user_id"] == "user_docs_001", (
        submitted["authored_by_user_id"]
    )

    admin_restriction = api_client.restrict_part_catalog_item(
        part["id"],
        factories.restriction_payload(restriction_reason="arc flash risk"),
        ADMIN,
    )
    validate_error(admin_restriction, "ERR_FORBIDDEN_ROLE", 403)
    assert fixtures.read_part(part["id"])["status"] == "PUBLISHED", (
        "the admin who created the part cannot restrict it"
    )

    author_approval = api_client.review_manual_revision(
        revision["id"],
        factories.review_decision_payload("APPROVE", review_note="looks fine to me"),
        DOCS,
    )
    validate_error(author_approval, "ERR_FORBIDDEN_ROLE", 403)

    approved = fixtures.review_revision(
        revision["id"], "APPROVE", SAFETY, review_note="coverage verified"
    )
    assert approved["status"] == "APPROVED", approved["status"]
    assert approved["reviewed_by_user_id"] == "user_safety_001", (
        approved["reviewed_by_user_id"]
    )

    author_publication = api_client.publish_manual_revision(revision["id"], DOCS, {})
    validate_error(author_publication, "ERR_FORBIDDEN_ROLE", 403)

    published = fixtures.publish_revision(revision["id"], SAFETY)
    assert published["status"] == "PUBLISHED", (
        f"publication is the reviewer's to make, got {published['status']}"
    )

    restricted = fixtures.restrict_part(
        part["id"],
        SAFETY,
        safety_class="SAFETY_RESTRICTED_HIGH_VOLTAGE",
        restriction_reason="arc flash risk",
    )
    assert restricted["status"] == "RESTRICTED", restricted["status"]
    assert restricted["safety_class"] == "SAFETY_RESTRICTED_HIGH_VOLTAGE", (
        f"the body's replacement class overwrites the old one, got "
        f"{restricted['safety_class']}"
    )


def test_attestation_is_the_officers_alone_while_the_sweep_and_the_clock_stay_shared():
    """PRD §2.1: "A `ComplianceOfficer` alone may attest an obligation, and shares profile
    creation, obligation creation, compliance sweeps, authorization decisions and clock
    movement with the `ProgramAdmin`."
    PRD §3.2: "The **compliance sweep** is the batch counterpart, available to a
    `ComplianceOfficer` or `ProgramAdmin`, optionally narrowed to a single `model_id` and
    otherwise covering every obligation in the system."
    PRD §3.2: "A successful attestation stores `last_attested_at` from the logical clock,
    `last_attested_by_user_id` from the caller's `X-User-ID`, and the
    `documentation_verified` flag, then rolls the model's posture up again; an `ATTESTED`
    row counts as open, never as breached, so the posture drops back to `OPEN` or `WATCH`
    when no sibling obligation is breached."

    Design: Corner/rbac/compliance_officer_alone_may_attest_and_the_sweep_and_clock_stay_shared
    """
    fixtures.create_region(region_code="US-CA")
    model = fixtures.create_model(
        model_code="CRX-R3",
        product_family="CRX",
        market_release_date="2024-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )
    part = fixtures.create_part(sku="SKU-R3-A", list_price_cents=1000)
    fixtures.create_compatibility(
        part["id"],
        model["id"],
        effective_from="2024-02-01T00:00:00Z",
        install_minutes=20,
    )
    fixtures.publish_part(part["id"])
    fixtures.publish_disassembly_guide(
        model["id"], ["SKU-R3-A"], safety_warning_count=2
    )

    obligation = fixtures.create_obligation(model["id"], "US-CA", ADMIN)
    assert obligation["status"] == "OPEN", (
        f"the obligation create is shared with the admin, got {obligation['status']}"
    )

    admin_attestation = api_client.attest_obligation(
        obligation["id"],
        factories.attestation_payload(attestation_note="admin sign-off"),
        ADMIN,
    )
    validate_error(admin_attestation, "ERR_FORBIDDEN_ROLE", 403)

    reviewer_sweep = api_client.run_compliance_sweep(
        factories.compliance_sweep_payload(model_id=model["id"]), SAFETY
    )
    validate_error(reviewer_sweep, "ERR_FORBIDDEN_ROLE", 403)

    author_clock = api_client.set_clock(
        factories.clock_payload("2026-08-02T00:00:00Z"), DOCS
    )
    validate_error(author_clock, "ERR_FORBIDDEN_ROLE", 403)

    admin_sweep = fixtures.run_sweep(ADMIN, model_id=model["id"])
    assert admin_sweep["swept_obligation_count"] == 1, (
        f"the admin may sweep the one obligation in scope, got "
        f"{admin_sweep['swept_obligation_count']}"
    )
    assert admin_sweep["breached_obligation_ids"] == [], (
        admin_sweep["breached_obligation_ids"]
    )

    fixtures.move_clock("2026-08-02T00:00:00Z", COMPLIANCE)

    attested = validate_success(
        api_client.attest_obligation(
            obligation["id"],
            factories.attestation_payload(attestation_note="officer sign-off"),
            COMPLIANCE,
        ),
        200,
    )
    assert attested["status"] == "ATTESTED", (
        f"attestation is the officer's exclusive write, got {attested['status']}"
    )
    assert attested["last_attested_by_user_id"] == "user_compliance_001", (
        attested["last_attested_by_user_id"]
    )
    assert attested["last_attested_at"].startswith("2026-08-02T00:00:00"), (
        f"the officer's own clock write took effect, got {attested['last_attested_at']}"
    )
    assert fixtures.read_model(model["id"])["compliance_posture"] == "OPEN", (
        "an attested row counts as open, never as breached"
    )


def test_root_cause_analysis_is_the_engineers_alone_and_the_gate_precedes_the_lookup():
    """PRD §2.1: "A `FailureAnalysisEngineer` alone may record a root cause on a returned
    unit, and shares the credit decision with the `ProgramAdmin`."
    PRD §2.1: "`SelfRepairCustomer` and `RepairProviderTech` share the whole buyer flow
    and defective-return filing."
    PRD §2.9: "**Role admissibility** — unknown or missing role (`ERR_UNAUTHORIZED`), then
    missing user id on an identity-recording write (`ERR_MISSING_USER_ID`), then a known
    role that the endpoint does not authorise (`ERR_FORBIDDEN_ROLE`)."
    PRD §2.9: "**Referential resolution** — the twelve not-found codes of §2.8, then
    `ERR_REGION_PROFILE_NOT_FOUND`, then nested-ownership not-found, then
    supersession-graph refusals (`ERR_SUPERSESSION_CYCLE`, then
    `ERR_SUPERSESSION_CLASS_MISMATCH`)."
    PRD §2.8: "Each identifier has its own not-found code: `model_id` yields
    `ERR_MODEL_NOT_FOUND`, `part_id` yields `ERR_PART_NOT_FOUND`, `compatibility_id`
    yields `ERR_COMPATIBILITY_NOT_FOUND`, `revision_id` yields
    `ERR_MANUAL_REVISION_NOT_FOUND`, `assessment_id` yields `ERR_ASSESSMENT_NOT_FOUND`,
    `order_id` yields `ERR_ORDER_NOT_FOUND`, `line_id` yields
    `ERR_ORDER_LINE_NOT_FOUND`, `provider_id` yields `ERR_PROVIDER_NOT_FOUND`,
    `certification_id` yields `ERR_CERTIFICATION_NOT_FOUND`, `case_id` yields
    `ERR_RETURN_CASE_NOT_FOUND`, `obligation_id` yields `ERR_OBLIGATION_NOT_FOUND`, and
    `acknowledgment_id` yields `ERR_ACKNOWLEDGMENT_NOT_FOUND`."

    Design: Corner/rbac/failure_analysis_engineer_alone_may_assign_a_root_cause_and_the_buyer_is_rejected_on_credit
    """
    analysis_payload = factories.failure_analysis_payload(
        "MANUFACTURING_DEFECT", True, analysis_note="solder void"
    )

    admin_analysis = api_client.record_failure_analysis(
        _UNKNOWN_CASE, analysis_payload, ADMIN
    )
    validate_error(admin_analysis, "ERR_FORBIDDEN_ROLE", 403)

    buyer_analysis = api_client.record_failure_analysis(
        _UNKNOWN_CASE, analysis_payload, CUSTOMER
    )
    validate_error(buyer_analysis, "ERR_FORBIDDEN_ROLE", 403)

    engineer_receipt = api_client.receive_defective_return(
        _UNKNOWN_CASE, FAILURE_ENGINEER
    )
    validate_error(engineer_receipt, "ERR_FORBIDDEN_ROLE", 403)

    buyer_decision = api_client.decide_defective_credit(
        _UNKNOWN_CASE, factories.credit_decision_payload("ISSUE_CREDIT"), CUSTOMER
    )
    validate_error(buyer_decision, "ERR_FORBIDDEN_ROLE", 403)

    engineer_decision = api_client.decide_defective_credit(
        _UNKNOWN_CASE,
        factories.credit_decision_payload("ISSUE_CREDIT"),
        FAILURE_ENGINEER,
    )
    validate_error(engineer_decision, "ERR_RETURN_CASE_NOT_FOUND", 404)
    assert engineer_decision.status_code == 404, (
        "a role the endpoint authorises falls through the gate to the case lookup, which "
        f"is what proves the ordering; got {engineer_decision.status_code}"
    )

    assert _count(api_client.list_defective_returns(FAILURE_ENGINEER)) == 0, (
        "no case was ever filed, and the reads are open to the engineer"
    )


def test_the_buyer_flow_is_shared_while_the_fulfilment_writes_stay_with_the_admin():
    """PRD §2.1: "`SelfRepairCustomer` and `RepairProviderTech` share the whole buyer flow
    and defective-return filing."
    PRD §2.1: "A `ProgramAdmin` alone may register product models and drive both lifecycle
    actions, create and publish catalog items, register compatibility rows, deliver an
    order, book in a core return, register providers and start their training, void a
    certification, and book in a defective unit."
    PRD §4: "| `POST` | `/repair-program/parts-orders` | Open a parts order against a
    valid eligibility ruling, consuming that ruling. | `SelfRepairCustomer`,
    `RepairProviderTech` |"
    PRD §4: "| `POST` | `/repair-program/defective-returns` | File a defective return case
    against a delivered order line. | `SelfRepairCustomer`, `RepairProviderTech` |"
    PRD §4: "| `POST` |
    `/repair-program/parts-orders/{order_id}/lines/{line_id}/authenticate` | Verify the
    pairing token on a delivered order line, marking it authentic or counterfeit-suspect.
    | `ProgramAdmin`, `RepairProviderTech`, `SelfRepairCustomer` |"
    PRD §4: "| `POST` | `/repair-program/parts-orders/{order_id}/cancel` | Cancel a
    non-terminal order, releasing any provisional core deposit and reversing committed
    core liability. | `SelfRepairCustomer`, `RepairProviderTech`, `ProgramAdmin` |"

    Design: Corner/rbac/buyer_roles_share_the_order_flow_and_are_forbidden_from_fulfilment_writes
    """
    admin_order = api_client.create_parts_order(
        factories.parts_order_payload(_UNKNOWN_ASSESSMENT, "US-CA"), ADMIN
    )
    validate_error(admin_order, "ERR_FORBIDDEN_ROLE", 403)

    admin_return = api_client.create_defective_return(
        factories.defective_return_payload(_UNKNOWN_LINE, 1), ADMIN
    )
    validate_error(admin_return, "ERR_FORBIDDEN_ROLE", 403)

    tech_delivery = api_client.deliver_order(_UNKNOWN_ORDER, TECH)
    validate_error(tech_delivery, "ERR_FORBIDDEN_ROLE", 403)

    buyer_core_receipt = api_client.book_core_return(
        _UNKNOWN_ORDER, factories.core_return_payload("2026-08-01T00:00:00Z"), CUSTOMER
    )
    validate_error(buyer_core_receipt, "ERR_FORBIDDEN_ROLE", 403)

    author_authentication = api_client.authenticate_line(
        _UNKNOWN_ORDER,
        _UNKNOWN_LINE,
        factories.authenticate_payload("TOK-BOGUS"),
        DOCS,
    )
    validate_error(author_authentication, "ERR_FORBIDDEN_ROLE", 403)

    tech_disclosure = api_client.request_disclosure(_UNKNOWN_ORDER, TECH)
    validate_error(tech_disclosure, "ERR_ORDER_NOT_FOUND", 404)

    admin_cancel = api_client.cancel_order(
        _UNKNOWN_ORDER,
        factories.cancellation_payload(cancellation_reason="changed my mind"),
        ADMIN,
    )
    validate_error(admin_cancel, "ERR_ORDER_NOT_FOUND", 404)

    assert _count(api_client.list_parts_orders(ADMIN, params={"limit": 50})) == 0, (
        "not one of the seven calls created anything"
    )
    assert _count(api_client.list_defective_returns(ADMIN, params={"limit": 50})) == 0, (
        "not one of the seven calls created anything"
    )


def test_self_review_is_forbidden_by_identity_even_when_the_author_holds_the_role():
    """PRD §2.11: "On documentation, the individual whose `X-User-ID` was recorded as a
    revision's `authored_by_user_id` may never supply that revision's review decision; the
    attempt is refused with `ERR_SELF_REVIEW_FORBIDDEN` (403)."
    PRD §2.11: "This holds even when the author holds the `SafetyReviewer` role —
    authoring and reviewing are separated by identity, not by role."
    PRD §3.4: "A rejection returns the revision from `IN_REVIEW` to `DRAFT`, increments
    `rejection_cycle_count` by one, and stores both `reviewed_by_user_id` and the note; it
    too requires `rejection_cycle_count` to be below three beforehand, otherwise
    `ERR_REVISION_CYCLE_CAP_REACHED`."
    PRD §3.4: "**Publication** is likewise a `SafetyReviewer` action and moves `APPROVED`
    to `PUBLISHED`."
    PRD §3.4: "The body may supply an `effective_from`; when it is omitted the publication
    effective instant defaults to the logical clock, and `published_at` is stamped from the
    logical clock either way."

    Design: Corner/rbac/segregation_of_duties_on_review_is_user_scoped_not_role_scoped
    """
    model = fixtures.create_model(
        model_code="CRX-R6",
        product_family="CRX",
        market_release_date="2024-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )
    revision = fixtures.create_draft_revision(
        model["id"],
        SAFETY,
        doc_type="DISASSEMBLY_GUIDE",
        covered_part_skus=["SKU-R6-A"],
        safety_warning_count=3,
    )
    assert revision["authored_by_user_id"] == "user_safety_001", (
        f"a safety reviewer may legitimately author a revision, got "
        f"{revision['authored_by_user_id']}"
    )
    assert revision["revision_number"] == 1, revision["revision_number"]

    submitted = fixtures.submit_revision(revision["id"], SAFETY)
    assert submitted["status"] == "IN_REVIEW", submitted["status"]

    self_approval = api_client.review_manual_revision(
        revision["id"],
        factories.review_decision_payload("APPROVE", review_note="my own work is fine"),
        SAFETY,
    )
    validate_error(self_approval, "ERR_SELF_REVIEW_FORBIDDEN", 403)

    self_rejection = api_client.review_manual_revision(
        revision["id"],
        factories.review_decision_payload(
            "REJECT", review_note="self rejection is still self review"
        ),
        SAFETY,
    )
    validate_error(self_rejection, "ERR_SELF_REVIEW_FORBIDDEN", 403)

    held = get_success_data(api_client.get_manual_revision(revision["id"], SAFETY))
    assert held["rejection_cycle_count"] == 0, (
        f"a refused decision increments no cycle counter, got "
        f"{held['rejection_cycle_count']}"
    )
    assert held["status"] == "IN_REVIEW", held["status"]

    approved = fixtures.review_revision(
        revision["id"], "APPROVE", SAFETY_ALT, review_note="independent review complete"
    )
    assert approved["status"] == "APPROVED", (
        f"a second reviewer identity clears the guard, got {approved['status']}"
    )
    assert approved["reviewed_by_user_id"] == "user_safety_002", (
        approved["reviewed_by_user_id"]
    )
    assert approved["rejection_cycle_count"] == 0, approved["rejection_cycle_count"]

    published = fixtures.publish_revision(revision["id"], SAFETY)
    assert published["status"] == "PUBLISHED", (
        f"publication carries no user-level guard, so the author may perform it, got "
        f"{published['status']}"
    )
    assert published["published_at"].startswith("2026-08-01T00:00:00"), (
        published["published_at"]
    )


def test_the_catalog_list_is_open_to_all_but_the_three_analytic_reads_are_not():
    """PRD §2.1: "A request whose role is one of the seven but is not among the roles the
    target endpoint authorises is rejected with `ERR_FORBIDDEN_ROLE` (403)."
    PRD §2.1: "A technician whose user id resolves to a different provider, or resolves to
    no provider at all, is rejected with `ERR_PROVIDER_SCOPE_VIOLATION` (403)."
    PRD §4: "| `GET` | `/repair-program/part-catalog-items` | List catalog items,
    filterable by part class, safety class, status and superseded predecessor. | All roles
    |"
    PRD §4: "| `GET` | `/repair-program/part-catalog-items/{part_id}/demand-forecast` |
    Compute the long-tail demand forecast and recommended stock level for one part on one
    model. | `ProgramAdmin`, `ComplianceOfficer` |"
    PRD §4: "| `GET` | `/repair-program/repair-providers/{provider_id}/compliance-score` |
    Compute the provider's compliance score, coverage ratio, breach count and access tier
    band under the chosen variant. | `ProgramAdmin`, `ComplianceOfficer`,
    `RepairProviderTech` |"
    PRD §4: "| `GET` | `/repair-program/part-catalog-items/{part_id}/order-lines` | List
    the order lines that reference one catalog item. | `ProgramAdmin`, `SafetyReviewer`,
    `FailureAnalysisEngineer` |"

    Design: Corner/rbac/most_reads_are_shared_but_the_forecast_score_and_line_history_are_forbidden_to_buyers
    """
    fixtures.create_region(region_code="US-CA")
    model = fixtures.create_model(
        model_code="CRX-R7",
        product_family="CRX",
        market_release_date="2024-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )
    part = fixtures.create_part(sku="SKU-R7-A", list_price_cents=1000)
    fixtures.create_compatibility(
        part["id"],
        model["id"],
        effective_from="2024-02-01T00:00:00Z",
        install_minutes=20,
    )
    fixtures.publish_part(part["id"])
    provider = fixtures.create_provider("US-CA", technician_count=4)

    assert _count(api_client.list_part_catalog_items(FAILURE_ENGINEER)) == 1, (
        "the catalog list is shared by every role"
    )
    assert _count(api_client.list_part_catalog_items(CUSTOMER)) == 1, (
        "the catalog list is shared by every role"
    )

    buyer_forecast = api_client.get_demand_forecast(
        part["id"],
        CUSTOMER,
        params={
            "model_id": model["id"],
            "horizon_months": 6,
            "variant": "TRAILING_ONLY",
        },
    )
    validate_error(buyer_forecast, "ERR_FORBIDDEN_ROLE", 403)

    reviewer_score = api_client.get_provider_compliance_score(
        provider["id"], SAFETY, params={"variant": "ROLLING_ATTESTED"}
    )
    validate_error(reviewer_score, "ERR_FORBIDDEN_ROLE", 403)

    buyer_line_history = api_client.list_order_lines_for_part(part["id"], CUSTOMER)
    validate_error(buyer_line_history, "ERR_FORBIDDEN_ROLE", 403)

    assert _count(api_client.list_order_lines_for_part(part["id"], FAILURE_ENGINEER)) == 0, (
        "the same path is open to the failure analysis engineer and holds no lines yet"
    )

    unresolved_tech = api_client.get_provider_compliance_score(
        provider["id"], TECH, params={"variant": "ROLLING_ATTESTED"}
    )
    validate_error(unresolved_tech, "ERR_PROVIDER_SCOPE_VIOLATION", 403)
