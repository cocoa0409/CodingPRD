"""Payload factories — one per entity, input fields only.

Each factory returns a request body with sensible defaults; pass **overrides to
control any field, or pass a field as None and pop it to omit it.
"""

DEFAULTS = {
    "ORG_NAME": "Test Org",
    "CLAUSE_KEY": "GENERIC_CLAUSE",
    "STANDARD_TEXT": "standard text",
    "CONTRACT_TEMPLATE_NAME": "Test Template",
    "COUNTERPARTY_NAME": "Beta Co",
    "CONTRACT_TITLE": "Test Contract",
    "JUSTIFICATION": "negotiated terms are acceptable",
    "OBLIGATION_DESCRIPTION": "deliver report",
}


def create_organization_payload(**overrides) -> dict:
    """Organization create body. Only `name` is required; threshold/lead-days
    are optional with server-side defaults, so they are omitted unless overridden."""
    payload = {"name": DEFAULTS["ORG_NAME"]}
    payload.update(overrides)
    return payload


def create_clause_template_payload(organization_id, **overrides) -> dict:
    """ClauseTemplate create body. Required: organization_id, clause_key,
    category, standard_text, risk_weight. is_mandatory is optional (default false)."""
    payload = {
        "organization_id": organization_id,
        "clause_key": DEFAULTS["CLAUSE_KEY"],
        "category": "OTHER",
        "standard_text": DEFAULTS["STANDARD_TEXT"],
        "risk_weight": 0,
    }
    payload.update(overrides)
    return payload


def create_contract_template_payload(organization_id, clause_template_ids, **overrides) -> dict:
    """ContractTemplate create body. Required: organization_id, name,
    clause_template_ids. default_term_months / auto_renew_default optional."""
    payload = {
        "organization_id": organization_id,
        "name": DEFAULTS["CONTRACT_TEMPLATE_NAME"],
        "clause_template_ids": list(clause_template_ids),
    }
    payload.update(overrides)
    return payload


def create_contract_payload(organization_id, contract_template_id, **overrides) -> dict:
    """Contract create body. Required: organization_id, contract_template_id,
    counterparty_name, title. term_months / auto_renew optional (default from template)."""
    payload = {
        "organization_id": organization_id,
        "contract_template_id": contract_template_id,
        "counterparty_name": DEFAULTS["COUNTERPARTY_NAME"],
        "title": DEFAULTS["CONTRACT_TITLE"],
    }
    payload.update(overrides)
    return payload


def clause_entry(clause_template_id, text="proposed text", is_deviation=False) -> dict:
    """One entry of a ContractVersion.clauses array."""
    return {
        "clause_template_id": clause_template_id,
        "text": text,
        "is_deviation": is_deviation,
    }


def create_version_payload(contract_id, clauses, expected_contract_version,
                           authored_by_party="INTERNAL", **overrides) -> dict:
    """ContractVersion create body. clauses is a list of clause_entry dicts."""
    payload = {
        "contract_id": contract_id,
        "authored_by_party": authored_by_party,
        "clauses": list(clauses),
        "expected_contract_version": expected_contract_version,
    }
    payload.update(overrides)
    return payload


def submit_payload(expected_contract_version, **overrides) -> dict:
    """Submit body. required_approver_count optional (default 1)."""
    payload = {"expected_contract_version": expected_contract_version}
    payload.update(overrides)
    return payload


def signer_entry(signer_party, signer_name) -> dict:
    """One entry of the send-for-signature `signers` list."""
    return {"signer_party": signer_party, "signer_name": signer_name}


def send_for_signature_payload(expected_contract_version, signers, **overrides) -> dict:
    """send-for-signature body. signers is a list of signer_entry dicts."""
    payload = {
        "expected_contract_version": expected_contract_version,
        "signers": list(signers),
    }
    payload.update(overrides)
    return payload


def default_signers() -> list:
    """A complete signer list (one INTERNAL + one COUNTERPARTY)."""
    return [
        signer_entry("INTERNAL", "Us"),
        signer_entry("COUNTERPARTY", "Them"),
    ]


def occ_payload(expected_contract_version, **overrides) -> dict:
    """Body for the OCC-guarded action endpoints (renew/terminate/cancel)."""
    payload = {"expected_contract_version": expected_contract_version}
    payload.update(overrides)
    return payload


def create_obligation_payload(contract_id, due_date, **overrides) -> dict:
    """Obligation create body. Required: contract_id, description, owner_party, due_date."""
    payload = {
        "contract_id": contract_id,
        "description": DEFAULTS["OBLIGATION_DESCRIPTION"],
        "owner_party": "COUNTERPARTY",
        "due_date": due_date,
    }
    payload.update(overrides)
    return payload


def create_deviation_approval_payload(contract_id, contract_version_id, clause_template_id, **overrides) -> dict:
    """DeviationApproval create body. Required: contract_id, contract_version_id,
    clause_template_id, justification."""
    payload = {
        "contract_id": contract_id,
        "contract_version_id": contract_version_id,
        "clause_template_id": clause_template_id,
        "justification": DEFAULTS["JUSTIFICATION"],
    }
    payload.update(overrides)
    return payload


def approval_step_payload(approval_workflow_id, decision="APPROVE", **overrides) -> dict:
    """ApprovalStep create body. Required: approval_workflow_id, decision."""
    payload = {
        "approval_workflow_id": approval_workflow_id,
        "decision": decision,
    }
    payload.update(overrides)
    return payload


def decide_payload(decision, **overrides) -> dict:
    """deviation-approvals/{id}/decide body. Required: decision (GRANT|DENY)."""
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601) -> dict:
    """Logical-clock set body."""
    return {"to_iso8601": to_iso8601}
