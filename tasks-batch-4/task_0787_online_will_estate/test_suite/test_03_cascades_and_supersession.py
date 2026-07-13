"""Transitive cascades (cancel → docs → grants; execute → supersede → grants) and
the conservation invariants they preserve.
"""
from test_helpers import (
    validate_success, validate_paginated, get_success_data,
    make_active_subscription, add_beneficiary, add_asset, generate_document, execute_document,
    setup_executed_will_with_share_grant, NOTARY,
)


def _executed_will_v1_then_v2_generated():
    """Active subscription with an EXECUTED WILL v1 and a GENERATED WILL v2.
    Returns (sub, hdr, doc1, doc2)."""
    member, sub, hdr = make_active_subscription(plan_tier="PLUS", base_price_cents=20000)
    add_beneficiary(sub["id"], hdr, allocation_pct=100)
    _q1, doc1 = generate_document(sub["id"], hdr, "WILL", "CA")
    doc1 = execute_document(doc1["id"], witnesses_count=2)
    _q2, doc2 = generate_document(sub["id"], hdr, "WILL", "CA")
    return sub, hdr, doc1, doc2


# ─── Difficulty: transitive_cascade / cancel_subscription_revokes_docs_and_grants ─
def test_cancel_revokes_document(api):
    """PRD §2.8: "When a subscription is cancelled, every non-terminal `EstateDocument`
    of that subscription transitions to `REVOKED`."

    Design: Difficulty/transitive_cascade/cancel_subscription_revokes_docs_and_grants
    """
    ctx = setup_executed_will_with_share_grant()
    sub, hdr, doc = ctx["subscription"], ctx["headers"], ctx["document"]
    cancelled = validate_success(api.cancel_subscription(sub["id"], hdr), 200)
    assert cancelled["status"] == "CANCELLED"
    doc_after = validate_success(api.get_document(doc["id"], hdr), 200)
    assert doc_after["status"] == "REVOKED"


def test_cancel_cascade_revokes_share_grant(api):
    """PRD §2.8: "Each document reaching `REVOKED` in turn revokes its own dependents:
    every `ACTIVE` `ShareGrant` whose `document_id` points at that document transitions
    to `REVOKED`, and any `AttorneyReview` of that document in a non-terminal status
    transitions to `CLOSED`."

    Design: Difficulty/transitive_cascade/cancel_subscription_revokes_docs_and_grants
    """
    ctx = setup_executed_will_with_share_grant()
    sub, hdr, doc, grant = ctx["subscription"], ctx["headers"], ctx["document"], ctx["grant"]
    validate_success(api.cancel_subscription(sub["id"], hdr), 200)
    grants, _meta = validate_paginated(api.list_document_share_grants(doc["id"], hdr))
    revoked = [g for g in grants if g["id"] == grant["id"]][0]
    assert revoked["status"] == "REVOKED"


# ─── Difficulty: transitive_cascade / execute_supersedes_prior_and_revokes_grants ─
def test_execute_supersedes_prior_executed_document(api):
    """PRD §2.8: "When a document reaches `EXECUTED` and a prior `EstateDocument` of the
    same subscription and same `document_type` was already `EXECUTED`, that prior
    document transitions to `SUPERSEDED`. The superseded document records the newer
    document's id in `superseded_by_id`, revokes every `ACTIVE` `ShareGrant` pointing at
    it, and closes any of its non-terminal `AttorneyReview` records."

    Design: Difficulty/transitive_cascade/execute_supersedes_prior_and_revokes_grants
    """
    member, sub, hdr = make_active_subscription(plan_tier="PLUS", base_price_cents=20000)
    add_beneficiary(sub["id"], hdr, allocation_pct=100)
    _q1, doc1 = generate_document(sub["id"], hdr, "WILL", "CA")
    doc1 = execute_document(doc1["id"], witnesses_count=2)
    get_success_data(api.create_share_grant(
        {"document_id": doc1["id"], "grantee_email": "exec@example.com",
         "scope": "VIEW", "expires_at": "2027-01-01T00:00:00Z"}, hdr))
    _q2, doc2 = generate_document(sub["id"], hdr, "WILL", "CA")

    doc2 = validate_success(api.execute_document(doc2["id"], {"witnesses_count": 2},
                                                 NOTARY), 200)
    assert doc2["status"] == "EXECUTED"
    doc1_after = validate_success(api.get_document(doc1["id"], hdr), 200)
    assert doc1_after["status"] == "SUPERSEDED"
    assert doc1_after["superseded_by_id"] == doc2["id"]


def test_supersession_revokes_prior_documents_share_grant(api):
    """PRD §2.8: "The superseded document records the newer document's id in
    `superseded_by_id`, revokes every `ACTIVE` `ShareGrant` pointing at it, and closes
    any of its non-terminal `AttorneyReview` records."

    Design: Difficulty/transitive_cascade/execute_supersedes_prior_and_revokes_grants
    """
    member, sub, hdr = make_active_subscription(plan_tier="PLUS", base_price_cents=20000)
    add_beneficiary(sub["id"], hdr, allocation_pct=100)
    _q1, doc1 = generate_document(sub["id"], hdr, "WILL", "CA")
    doc1 = execute_document(doc1["id"], witnesses_count=2)
    grant1 = get_success_data(api.create_share_grant(
        {"document_id": doc1["id"], "grantee_email": "exec@example.com",
         "scope": "VIEW", "expires_at": "2027-01-01T00:00:00Z"}, hdr))
    _q2, doc2 = generate_document(sub["id"], hdr, "WILL", "CA")

    validate_success(api.execute_document(doc2["id"], {"witnesses_count": 2}, NOTARY), 200)
    grants, _meta = validate_paginated(api.list_document_share_grants(doc1["id"], hdr))
    revoked = [g for g in grants if g["id"] == grant1["id"]][0]
    assert revoked["status"] == "REVOKED"


# ─── Difficulty: compensating_invariant / asset_earmark_reassign_conserves_assigned_value ─
def test_reassign_asset_earmark_to_second_beneficiary(api):
    """PRD §3.9: "An asset's earmark may also be set or changed afterward through the
    assign-beneficiary operation, which takes a `beneficiary_id` that must reference an
    existing `Beneficiary` of the same subscription".

    Design: Difficulty/compensating_invariant/asset_earmark_reassign_conserves_assigned_value
    """
    member, sub, hdr = make_active_subscription(plan_tier="PLUS", base_price_cents=20000)
    ben1 = add_beneficiary(sub["id"], hdr, full_name="Ben One", allocation_pct=50)
    ben2 = add_beneficiary(sub["id"], hdr, full_name="Ben Two", allocation_pct=50)
    asset = add_asset(sub["id"], hdr, asset_type="BANK", estimated_value_cents=50000,
                      funding_status="UNFUNDED", assigned_beneficiary_id=ben1["id"])
    reassigned = validate_success(
        api.assign_beneficiary(asset["id"], {"beneficiary_id": ben2["id"]}, hdr), 200)
    assert reassigned["assigned_beneficiary_id"] == ben2["id"]


def test_reassign_conserves_total_assigned_value(api):
    """PRD §3.9: "The summary also reports `total_assigned_value_cents`, the sum of
    `estimated_value_cents` across assets that carry an `assigned_beneficiary_id`".

    Design: Difficulty/compensating_invariant/asset_earmark_reassign_conserves_assigned_value
    """
    member, sub, hdr = make_active_subscription(plan_tier="PLUS", base_price_cents=20000)
    ben1 = add_beneficiary(sub["id"], hdr, full_name="Ben One", allocation_pct=50)
    ben2 = add_beneficiary(sub["id"], hdr, full_name="Ben Two", allocation_pct=50)
    asset = add_asset(sub["id"], hdr, asset_type="BANK", estimated_value_cents=50000,
                      funding_status="UNFUNDED", assigned_beneficiary_id=ben1["id"])
    validate_success(api.assign_beneficiary(asset["id"], {"beneficiary_id": ben2["id"]}, hdr), 200)
    summary = validate_success(api.get_estate_summary(sub["id"], hdr), 200)
    assert summary["total_assigned_value_cents"] == 50000


# ─── Difficulty: compensating_invariant / execute_supersede_conserves_executed_count ─
def test_execute_v2_supersedes_v1(api):
    """PRD §2.8: "When a document reaches `EXECUTED` and a prior `EstateDocument` of the
    same subscription and same `document_type` was already `EXECUTED`, that prior
    document transitions to `SUPERSEDED`."

    Design: Difficulty/compensating_invariant/execute_supersede_conserves_executed_count
    """
    sub, hdr, doc1, doc2 = _executed_will_v1_then_v2_generated()
    doc2 = validate_success(api.execute_document(doc2["id"], {"witnesses_count": 2},
                                                 NOTARY), 200)
    assert doc2["status"] == "EXECUTED"
    doc1_after = validate_success(api.get_document(doc1["id"], hdr), 200)
    assert doc1_after["status"] == "SUPERSEDED"


def test_supersession_conserves_executed_will_count(api):
    """PRD §3.8: "The sequence `GENERATED → EXECUTED → SUPERSEDED` (or
    `PENDING_EXECUTION → EXECUTED` for the reviewed path) is thus how a member's newest
    will or trust replaces its predecessor while cleanly retiring the old document's
    shares."

    Design: Difficulty/compensating_invariant/execute_supersede_conserves_executed_count
    """
    sub, hdr, doc1, doc2 = _executed_will_v1_then_v2_generated()
    validate_success(api.execute_document(doc2["id"], {"witnesses_count": 2}, NOTARY), 200)
    docs, _meta = validate_paginated(api.list_subscription_documents(sub["id"], hdr))
    executed_wills = [d for d in docs
                      if d["document_type"] == "WILL" and d["status"] == "EXECUTED"]
    assert len(executed_wills) == 1
