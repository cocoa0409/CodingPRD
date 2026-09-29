"""Multi-hop system cascades (PRD 3.2/3.3 escalation, PRD 3.9 remand)."""

import db
from services import record, rollups


def escalate_classification(action):
    """HOP 2 + HOP 3 of the extraordinary-circumstance cascade.

    Fires when extraordinary_circumstance_flag has just become true. Escalation
    only ever moves CATEGORICAL_EXCLUSION up to ENVIRONMENTAL_ASSESSMENT; there
    is no downgrade path of any kind.
    """
    if action["classification"] != "CATEGORICAL_EXCLUSION":
        return
    action["classification"] = "ENVIRONMENTAL_ASSESSMENT"
    if action["review_stage"] in ("CLASSIFIED", "SCOPING", "ANALYSIS", "DRAFT_PUBLISHED"):
        action["review_stage"] = "CLASSIFIED"
    db.touch(action)
    record.add_entry(
        action,
        "CLASSIFICATION_ESCALATED",
        "ProposedAction",
        action["id"],
        "Classification escalated to ENVIRONMENTAL_ASSESSMENT by extraordinary circumstance",
    )

    # HOP 3: the classification moved away from CATEGORICAL_EXCLUSION, so every
    # live CE memorandum of the action is superseded.
    for document in db.rows("documents"):
        if document["action_id"] != action["id"]:
            continue
        if document["document_type"] != "CE_MEMORANDUM":
            continue
        if document["publication_status"] not in ("DRAFT", "PUBLISHED"):
            continue
        document["publication_status"] = "SUPERSEDED"
        document["comment_status"] = "CLOSED"
        db.touch(document)
        record.add_entry(
            action,
            "DOCUMENT_SUPERSEDED",
            "NepaDocument",
            document["id"],
            "CE memorandum superseded by classification escalation",
        )


def vacate_decision(decision, action, office):
    """The remand cascade: vacatur, commitment release, ledger debit, documents."""
    decision["status"] = "VACATED"
    db.touch(decision)

    # HOP 2a: release every BINDING commitment.
    for commitment in db.rows("mitigations"):
        if commitment["decision_id"] != decision["id"]:
            continue
        if commitment["status"] != "BINDING":
            continue
        commitment["status"] = "RELEASED"
        commitment["monitoring_status"] = "RELEASED"
        db.touch(commitment)

    # HOP 2b: restore the office ledger to its exact pre-signature value.
    office["binding_obligation_cents"] = int(office["binding_obligation_cents"]) - int(
        decision["binding_obligation_cents"]
    )
    db.touch(office)

    # HOP 3: the FINAL document reverts on the publication axis only.
    for document in db.rows("documents"):
        if document["action_id"] != action["id"]:
            continue
        if document["publication_status"] != "FINAL":
            continue
        document["publication_status"] = "DRAFT"
        db.touch(document)

    if action["review_stage"] == "DECIDED":
        action["review_stage"] = "COMMENT_CLOSED"
        db.touch(action)

    record.add_entry(
        action,
        "DECISION_VACATED",
        "DecisionDocument",
        decision["id"],
        "Decision vacated on objection remand",
    )
    rollups.refresh_action(action)
