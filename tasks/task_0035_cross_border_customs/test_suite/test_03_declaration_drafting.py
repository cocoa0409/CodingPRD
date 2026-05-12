"""Order intake, draft declaration creation, lines, manual override review.

PRD anchors: §3.3 (order intake & draft creation), §3.4 (lines + manual
override + path to submission).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_party_pair,
    create_order,
    create_draft_declaration,
    setup_draft_declaration,
    create_hs_code,
    create_declaration_line_payload,
    create_declaration_payload,
    create_order_payload,
    review_override_payload,
    deprecate_hs_code,
    suspend_importer,
    make_declarant_headers,
    make_importer_headers,
    add_line,
    submit_declaration,
    start_review,
    approve_declaration,
    setup_under_review_declaration,
    assert_order,
    assert_declaration,
    assert_declaration_line,
)


# ---------------------------------------------------------------------------
# Order creation
# ---------------------------------------------------------------------------
def test_create_order_initial_status_pending_declaration(api):
    """PRD §3.3: "Newly created orders begin in PENDING_DECLARATION."
    """
    importer, declarant = create_party_pair()
    res = api.create_order(
        create_order_payload(importer["id"], declarant["id"]),
        make_declarant_headers(declarant["id"]),
    )
    order = validate_success(res, expected_status=201)
    assert_order(order)
    assert order["status"] == "PENDING_DECLARATION"


def test_cancel_order_in_pending_declaration(api):
    """PRD §3.3: "Cancelling the order transitions it to CANCELLED;
    cancellation is allowed only when no declaration exists for the order,
    or when the only existing declaration is still in DRAFT (in which
    case the cancellation deletes that draft as a side effect)."

    Claim: cancel on a PENDING_DECLARATION order with no declaration →
    status flips to CANCELLED.
    """
    importer, declarant = create_party_pair()
    order = create_order(importer, declarant)
    res = api.cancel_order(order["id"], make_importer_headers(importer["id"]))
    cancelled = validate_success(res)
    assert cancelled["status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# Draft declaration creation
# ---------------------------------------------------------------------------
def test_create_draft_declaration_copies_fields(api):
    """PRD §3.3: "The server copies declarant_id, trade_mode, and
    destination_country from the parent order onto the new declaration,
    sets submission_count to zero, and places the declaration in DRAFT."
    """
    ctx = setup_draft_declaration(add_lines=False)
    decl = ctx.declaration
    assert_declaration(decl)
    assert decl["status"] == "DRAFT"
    assert decl["submission_count"] == 0
    assert decl["declarant_id"] == ctx.declarant["id"]
    assert decl["trade_mode"] == ctx.order["trade_mode"]
    assert decl["destination_country"] == ctx.order["destination_country"]


def test_create_second_declaration_for_same_order_rejected(api):
    """PRD §3.3: "At most one declaration may exist for a given order in
    a non-terminal state ...; if a second declarant tries to create a
    parallel declaration on the same order, the second creation is
    rejected with ERR_DECLARATION_ALREADY_EXISTS."
    """
    ctx = setup_draft_declaration()
    res = api.create_declaration(
        create_declaration_payload(ctx.order["id"]),
        make_declarant_headers(ctx.declarant["id"]),
    )
    validate_error(res, "ERR_DECLARATION_ALREADY_EXISTS", expected_status=409)


def test_create_declaration_when_importer_suspended(api):
    """PRD §3.3: "If the importer was suspended at the moment of creation,
    the creation is rejected with ERR_IMPORTER_SUSPENDED."
    """
    importer, declarant = create_party_pair()
    order = create_order(importer, declarant)
    suspend_importer(importer["id"])
    res = api.create_declaration(
        create_declaration_payload(order["id"]),
        make_declarant_headers(declarant["id"]),
    )
    validate_error(res, "ERR_IMPORTER_SUSPENDED", expected_status=409)


# ---------------------------------------------------------------------------
# Declaration lines and HS-code references
# ---------------------------------------------------------------------------
def test_add_line_with_active_hs_code(api):
    """PRD §3.4: "Lines are added one at a time via the line-creation
    capability while the parent declaration remains in DRAFT."
    """
    ctx = setup_draft_declaration(add_lines=False)
    line = add_line(
        ctx.declaration, ctx.declarant,
        order_line_index=0, hs_code_id=ctx.ref["hs_code"]["id"],
    )
    assert_declaration_line(line)
    assert line["override_review_status"] == "NOT_APPLICABLE"


def test_add_line_with_deprecated_hs_code_rejected(api):
    """PRD §3.4: "The HS code referenced by hs_code_id must be in ACTIVE
    status at the moment of line creation; referencing a DEPRECATED code
    is rejected with ERR_HS_CODE_DEPRECATED."
    """
    ctx = setup_draft_declaration(add_lines=False)
    deprecate_hs_code(ctx.ref["hs_code"]["id"])
    res = api.add_declaration_line(
        ctx.declaration["id"],
        create_declaration_line_payload(
            order_line_index=0, hs_code_id=ctx.ref["hs_code"]["id"]
        ),
        make_declarant_headers(ctx.declarant["id"]),
    )
    validate_error(res, "ERR_HS_CODE_DEPRECATED", expected_status=409)


def test_manual_override_sets_pending(api):
    """PRD §3.4: "When the classification source on creation is
    MANUAL_OVERRIDE, the line's override_review_status is set to
    PENDING and a customs officer must subsequently approve or reject
    the override."
    """
    ctx = setup_draft_declaration(add_lines=False)
    line = add_line(
        ctx.declaration, ctx.declarant,
        order_line_index=0, hs_code_id=ctx.ref["hs_code"]["id"],
        classification_source="MANUAL_OVERRIDE",
    )
    assert line["override_review_status"] == "PENDING"


def test_override_approve_flips_to_approved(api):
    """PRD §3.4: "An approved override flips the line's
    override_review_status to APPROVED; a rejected override flips it to
    REJECTED."
    """
    ctx = setup_draft_declaration(add_lines=False)
    line = add_line(
        ctx.declaration, ctx.declarant,
        order_line_index=0, hs_code_id=ctx.ref["hs_code"]["id"],
        classification_source="MANUAL_OVERRIDE",
    )
    res = api.review_line_override(
        ctx.declaration["id"], line["id"],
        review_override_payload("APPROVE"),
        TEST_USERS["customs_officer_headers"],
    )
    decided = validate_success(res)
    assert decided["override_review_status"] == "APPROVED"


def test_override_reject_flips_to_rejected(api):
    """PRD §3.4: "a rejected override flips it to REJECTED."
    """
    ctx = setup_draft_declaration(add_lines=False)
    line = add_line(
        ctx.declaration, ctx.declarant,
        order_line_index=0, hs_code_id=ctx.ref["hs_code"]["id"],
        classification_source="MANUAL_OVERRIDE",
    )
    res = api.review_line_override(
        ctx.declaration["id"], line["id"],
        review_override_payload("REJECT"),
        TEST_USERS["customs_officer_headers"],
    )
    decided = validate_success(res)
    assert decided["override_review_status"] == "REJECTED"


def test_override_after_draft_rejected(api):
    """PRD §3.4: "The override action is allowed only while the parent
    declaration is still in DRAFT; if the declaration has already moved
    past draft, the override action is rejected with
    ERR_OVERRIDE_NOT_ALLOWED."
    """
    ctx = setup_draft_declaration(
        classification_source="MANUAL_OVERRIDE", add_lines=False,
    )
    line = add_line(
        ctx.declaration, ctx.declarant,
        order_line_index=0, hs_code_id=ctx.ref["hs_code"]["id"],
        classification_source="MANUAL_OVERRIDE",
    )
    # Approve override so the declaration can move forward.
    api.review_line_override(
        ctx.declaration["id"], line["id"],
        review_override_payload("APPROVE"),
        TEST_USERS["customs_officer_headers"],
    )
    # Submit & start_review → past DRAFT.
    submit_declaration(ctx.declaration, ctx.declarant)
    res = api.review_line_override(
        ctx.declaration["id"], line["id"],
        review_override_payload("REJECT"),
        TEST_USERS["customs_officer_headers"],
    )
    validate_error(res, "ERR_OVERRIDE_NOT_ALLOWED", expected_status=409)
