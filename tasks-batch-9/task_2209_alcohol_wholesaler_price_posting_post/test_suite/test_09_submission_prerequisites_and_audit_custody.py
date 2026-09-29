"""Which refusal a submission earns first, and how audit custody freezes an invoice."""

from test_helpers import (
    api_client,
    approve_brand,
    assert_price_schedule,
    assert_retailer_invoice,
    assess_audit,
    create_invoice_line_payload,
    read_audit,
    read_brand,
    read_invoice,
    read_item,
    read_schedule,
    read_wholesaler,
    set_license_status,
    setup_collected_audit,
    setup_draft_schedule,
    setup_licensee_base,
    validate_error,
    validate_success,
    void_audit,
)


def _suspended_licensee_with_pending_brand():
    """A draft August schedule whose brand is pending and whose licence is suspended."""
    scene = setup_licensee_base(approve_brand_registration=False)
    setup_draft_schedule(scene, posting_month="2026-08")
    set_license_status(scene["wholesaler"]["id"], "SUSPENDED")
    return scene


def test_suspended_licence_outranks_the_unregistered_brand_on_submission():
    """Two rules are broken at once and licence standing is the one that answers.

    PRD §2.10: "A suspended licensee may neither file nor invoice."

    Design: Difficulty/priority_pair_validation_conflict/suspended_license_business_safety_outranks_the_unregistered_brand_prerequisite_on_submit
    """
    scene = _suspended_licensee_with_pending_brand()

    response = api_client.submit_price_schedule(
        scene["schedule"]["id"], scene["agent_headers"]
    )

    validate_error(response, "ERR_LICENSE_NOT_ACTIVE", 409)

    schedule = read_schedule(scene["schedule"]["id"])
    assert_price_schedule(schedule)
    assert schedule["status"] == "DRAFT"
    assert schedule.get("filed_at") is None
    assert schedule.get("filed_by_user_id") is None
    assert read_brand(scene["brand"]["id"])["registration_status"] == "PENDING"


def test_reinstating_the_licence_exposes_the_brand_prerequisite_underneath():
    """Clear the higher rule and the lower one answers; clear both and the filing lands.

    PRD §3.2: "A brand that is still `PENDING`, a brand that was `REJECTED`, or an
    approved brand whose registration expires before the month the prices would take
    effect all produce the same refusal, `ERR_BRAND_NOT_REGISTERED`."

    Design: Difficulty/priority_pair_validation_conflict/suspended_license_business_safety_outranks_the_unregistered_brand_prerequisite_on_submit
    """
    scene = _suspended_licensee_with_pending_brand()
    set_license_status(scene["wholesaler"]["id"], "ACTIVE")

    refused = api_client.submit_price_schedule(
        scene["schedule"]["id"], scene["agent_headers"]
    )
    validate_error(refused, "ERR_BRAND_NOT_REGISTERED", 409)

    assert read_schedule(scene["schedule"]["id"])["status"] == "DRAFT"
    assert read_brand(scene["brand"]["id"])["registration_status"] == "PENDING"

    approve_brand(scene["brand"]["id"])
    accepted = api_client.submit_price_schedule(
        scene["schedule"]["id"], scene["agent_headers"]
    )
    submitted = validate_success(accepted, 200)

    assert submitted["status"] == "SUBMITTED"
    assert submitted["is_late"] is False

    wholesaler = read_wholesaler(scene["wholesaler"]["id"])
    assert wholesaler["late_filing_penalty_accrued_cents"] == 0
    assert wholesaler["penalty_exposure_cents"] == 0
    assert read_item(scene["items"][0]["id"])["status"] == "DRAFT"


def test_collected_audit_freezes_the_invoice_against_revalidation_and_new_lines():
    """Custody, not validation status, is what closes the document to the filer.

    PRD §3.9: "Every such flagged invoice is collected: its `audit_status` moves to
    `UNDER_AUDIT` and its `audit_id` is stamped with this audit's identifier, which also
    freezes it against further line additions and further validation."

    Design: Difficulty/cross_entity_state_dependency/retailer_invoice_revalidation_is_gated_by_the_collecting_compliance_audit_state
    """
    scene = setup_collected_audit()
    invoice_id = scene["invoice"]["id"]

    refused_validate = api_client.validate_retailer_invoice(
        invoice_id, scene["agent_headers"]
    )
    validate_error(refused_validate, "ERR_INVALID_STATE", 409)

    invoice = read_invoice(invoice_id)
    assert_retailer_invoice(invoice)
    assert invoice["audit_status"] == "UNDER_AUDIT"
    assert invoice["audit_id"] == scene["audit"]["id"]

    refused_line = api_client.create_invoice_line(
        create_invoice_line_payload(
            invoice_id, scene["items"][0]["id"], 120_000, 11_000, cases_quantity=1
        ),
        scene["agent_headers"],
    )
    validate_error(refused_line, "ERR_INVALID_STATE", 409)

    invoice = read_invoice(invoice_id)
    assert invoice["line_count"] == 1
    assert invoice["validation_status"] == "FLAGGED"
    assert invoice["off_posted_line_count"] == 1
    assert invoice["total_variance_cents"] == 5_000


def test_assessed_audit_keeps_the_invoice_frozen():
    """Assessment moves custody forward without releasing the document.

    PRD §3.9: "Every invoice this audit collected has its `audit_status` moved from
    `UNDER_AUDIT` to `ASSESSED`."

    Design: Difficulty/cross_entity_state_dependency/retailer_invoice_revalidation_is_gated_by_the_collecting_compliance_audit_state
    """
    scene = setup_collected_audit()
    invoice_id = scene["invoice"]["id"]

    assessed = assess_audit(scene["audit"]["id"])
    assert assessed["status"] == "ASSESSED"
    assert assessed["penalty_assessed_cents"] == 2_000

    invoice = read_invoice(invoice_id)
    assert invoice["audit_status"] == "ASSESSED"

    refused = api_client.validate_retailer_invoice(invoice_id, scene["agent_headers"])
    validate_error(refused, "ERR_INVALID_STATE", 409)

    invoice = read_invoice(invoice_id)
    assert invoice["validation_status"] == "FLAGGED"
    assert invoice["off_posted_line_count"] == 1
    assert invoice["total_variance_cents"] == 5_000


def test_voiding_the_audit_releases_the_invoice_for_revalidation():
    """Custody released, the filer may reprice and extend the document again.

    PRD §3.9: "A voided audit releases its invoices for revalidation and frees the month
    for a fresh audit; `VOID` is terminal."

    Design: Difficulty/cross_entity_state_dependency/retailer_invoice_revalidation_is_gated_by_the_collecting_compliance_audit_state
    """
    scene = setup_collected_audit()
    invoice_id = scene["invoice"]["id"]

    assess_audit(scene["audit"]["id"])
    voided = void_audit(scene["audit"]["id"])
    assert voided["status"] == "VOID"
    assert read_audit(scene["audit"]["id"])["status"] == "VOID"

    released = read_invoice(invoice_id)
    assert released["audit_status"] == "NOT_AUDITED"
    assert released.get("audit_id") is None

    revalidated = validate_success(
        api_client.validate_retailer_invoice(invoice_id, scene["agent_headers"]), 200
    )
    assert revalidated["validation_status"] == "FLAGGED"
    assert revalidated["off_posted_line_count"] == 1
    assert revalidated["total_variance_cents"] == 5_000

    appended = api_client.create_invoice_line(
        create_invoice_line_payload(
            invoice_id, scene["items"][0]["id"], 120_000, 11_000, cases_quantity=1
        ),
        scene["agent_headers"],
    )
    validate_success(appended, 201)
    assert read_invoice(invoice_id)["line_count"] == 2

    wholesaler = read_wholesaler(scene["wholesaler"]["id"])
    assert wholesaler["assessed_penalty_cents"] == 0
    assert wholesaler["off_posted_violation_count"] == 0
    assert wholesaler["penalty_exposure_cents"] == 0
