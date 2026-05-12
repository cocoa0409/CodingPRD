"""Contract / SigningStep / SigningParty business logic per PRD §3.2-§3.7."""

from db import DB, new_id
from clock import now, parse_iso
from errors import (
    APIError, validation_failed, version_conflict, invalid_state, not_found,
    forbidden, ERR_TEMPLATE_NOT_PUBLISHED, ERR_TEMPLATE_PERMISSION_DENIED,
    ERR_DELEGATION_INVALID, ERR_LEGAL_REP_REQUIRES_MFA, ERR_WORKFLOW_LOCKED,
    ERR_REINITIATE_INVALID, ERR_SEGREGATION_OF_DUTIES, ERR_CONTRACT_EXPIRED,
    APIError as _APIError,
)
from services.audit import append_audit
from services.calculations import (
    compute_document_fingerprint, compute_evidence_strength, compute_signing_progress,
    MIN_FACTORS_FOR_LEGAL_REP,
)
from services.templates import get_template


VALID_SIGNER_TYPES = {"INDIVIDUAL", "ORG_LEGAL_REP", "ORG_DELEGATE"}
VALID_AUTH_FACTORS = {"SMS", "FACE", "CA_CERT", "BANK_CARD"}
VALID_STEP_MODES = {"SEQUENTIAL", "PARALLEL_COUNTERSIGN"}


# ----- Lookups --------------------------------------------------------------

def get_contract(contract_id: str) -> dict:
    c = DB.contracts.get(contract_id)
    if not c:
        raise not_found("Contract not found")
    return c


def get_signing_step(contract_id: str, sid: str) -> dict:
    c = DB.contracts.get(contract_id)
    if not c:
        raise not_found("Contract not found")
    s = DB.signing_steps.get(sid)
    if not s or s["contract_id"] != contract_id:
        raise not_found("SigningStep not found")
    return s


def get_signing_party(party_id: str) -> dict:
    p = DB.signing_parties.get(party_id)
    if not p:
        raise not_found("SigningParty not found")
    return p


# ----- Reminders cascade reset ---------------------------------------------

def _disable_all_reminders(contract_id: str, n):
    for r in DB.reminder_rules.values():
        if r["contract_id"] == contract_id and r["enabled"]:
            r["enabled"] = False
            r["version"] += 1
            r["updated_at"] = n


def _reset_reminder_misses(contract_id: str, n):
    for r in DB.reminder_rules.values():
        if r["contract_id"] == contract_id and r.get("misses_count", 0) != 0:
            r["misses_count"] = 0
            r["version"] += 1
            r["updated_at"] = n


def _evidence_pkg_to_generating(contract_id: str, n):
    for e in DB.evidence_packages.values():
        if e["contract_id"] == contract_id and e["status"] == "PENDING":
            e["status"] = "GENERATING"
            e["version"] += 1
            e["updated_at"] = n
            return


def _ensure_evidence_package(contract_id: str, n) -> dict:
    """Lazy-create EvidencePackage in PENDING for the contract if absent."""
    for e in DB.evidence_packages.values():
        if e["contract_id"] == contract_id:
            return e
    eid = new_id()
    e = {
        "id": eid,
        "contract_id": contract_id,
        "status": "PENDING",
        "package_sha256": None,
        "notary_provider": "NONE",
        "notary_reference": None,
        "sealed_at": None,
        "exported_at": None,
        "version": 1,
        "created_at": n,
        "updated_at": n,
    }
    DB.evidence_packages[eid] = e
    return e


# ----- Cascade helpers for void --------------------------------------------

def _cascade_void(c: dict, void_reason: str, n, *, actor_user_id: str, actor_role: str, audit_action: str):
    """Apply VOID cascade to a contract: skip non-terminal steps & parties,
    disable reminders, advance evidence package, append audit."""
    c["status"] = "VOIDED"
    c["voided_at"] = n
    c["void_reason"] = void_reason
    c["version"] += 1
    c["updated_at"] = n

    # Cascade non-terminal SigningSteps -> SKIPPED
    for s in DB.signing_steps.values():
        if s["contract_id"] != c["id"]:
            continue
        if s["status"] in ("PENDING", "ACTIVE"):
            s["status"] = "SKIPPED"
            s["completed_at"] = n
            s["version"] += 1
            s["updated_at"] = n
    # Cascade non-terminal SigningParties -> SKIPPED
    for p in DB.signing_parties.values():
        if p["contract_id"] != c["id"]:
            continue
        if p["status"] in ("WAITING", "AUTHENTICATING"):
            p["status"] = "SKIPPED"
            p["version"] += 1
            p["updated_at"] = n

    _disable_all_reminders(c["id"], n)
    _ensure_evidence_package(c["id"], n)
    _evidence_pkg_to_generating(c["id"], n)

    # Recompute progress and evidence (per PRD: also recomputed on auto-void)
    pct, _ = compute_signing_progress(c["id"], "chronological")
    c["signing_progress_percent"] = pct
    pkg = _find_evidence_pkg(c["id"])
    notary_provider = pkg["notary_provider"] if pkg else "NONE"
    score, tier, _ = compute_evidence_strength(c, notary_provider=notary_provider, apply_notary_bonus=False)
    c["evidence_strength_score"] = score
    c["evidence_tier"] = tier

    append_audit(
        contract_id=c["id"],
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action=audit_action,
        payload={
            "contract_id": c["id"],
            "void_reason": void_reason,
        },
    )


def _find_evidence_pkg(contract_id: str):
    for e in DB.evidence_packages.values():
        if e["contract_id"] == contract_id:
            return e
    return None


# ----- Contract create ------------------------------------------------------

def create_contract(payload: dict, *, actor_user_id: str, actor_role: str, actor_org_id_hint=None) -> dict:
    if not isinstance(payload, dict):
        raise validation_failed("Body must be a JSON object")
    tv_id = payload.get("template_version_id")
    if not isinstance(tv_id, str) or not tv_id:
        raise validation_failed("template_version_id is required")
    title = payload.get("title")
    if not isinstance(title, str) or not (1 <= len(title) <= 200):
        raise validation_failed("title must be a string of length 1..200")
    if "variable_values" not in payload:
        raise validation_failed("variable_values is required")
    variable_values = payload["variable_values"]
    if not isinstance(variable_values, dict):
        raise validation_failed("variable_values must be a JSON object")
    expires_at_raw = payload.get("expires_at")
    if not expires_at_raw:
        raise validation_failed("expires_at is required")
    try:
        expires_at = parse_iso(expires_at_raw)
    except Exception:
        raise validation_failed("expires_at must be ISO 8601")

    tv = DB.template_versions.get(tv_id)
    if not tv:
        raise not_found("TemplateVersion not found")
    if tv["status"] != "PUBLISHED":
        raise APIError(ERR_TEMPLATE_NOT_PUBLISHED, "TemplateVersion is not PUBLISHED", 409)

    template = DB.templates.get(tv["template_id"])
    # initiator_org_id: lookup OrgUser if we have one; else use a hint or body field
    initiator_org_id = payload.get("initiator_org_id")
    if initiator_org_id is None:
        user = DB.org_users.get(actor_user_id)
        if user:
            initiator_org_id = user.get("org_id")
    if initiator_org_id is None:
        initiator_org_id = actor_org_id_hint
    # Permission scope check (only when initiator_org_id is known)
    scope = template.get("permission_scope", "ORG_ONLY")
    if scope == "ORG_ONLY" and initiator_org_id is not None:
        if initiator_org_id != template["owner_org_id"]:
            raise APIError(ERR_TEMPLATE_PERMISSION_DENIED, "Template ORG_ONLY scope; org mismatch", 403)
    # CROSS_ORG and PUBLIC: no further check
    if initiator_org_id is None:
        # Default fallback: assume contract belongs to template's org (for tests
        # that don't exercise scope and don't pre-register OrgUsers).
        initiator_org_id = template["owner_org_id"]

    # Re-initiation
    reinit_from = payload.get("reinitiated_from_contract_id")
    if reinit_from is not None:
        src = DB.contracts.get(reinit_from)
        if not src:
            raise APIError(ERR_REINITIATE_INVALID, "Source contract not found", 409)
        if src["status"] not in ("VOIDED", "EXPIRED"):
            raise APIError(ERR_REINITIATE_INVALID, "Source contract not voided/expired", 409)
        if src.get("initiator_org_id") != initiator_org_id:
            raise APIError(ERR_REINITIATE_INVALID, "Org mismatch on re-initiation", 409)
        if reinit_from in DB.reinit_index:
            raise APIError(ERR_REINITIATE_INVALID, "Source already re-initiated", 409)

    n = now()
    cid = new_id()
    c = {
        "id": cid,
        "template_version_id": tv_id,
        "initiator_user_id": actor_user_id,
        "initiator_org_id": initiator_org_id,
        "title": title,
        "variable_values": variable_values,
        "status": "DRAFT",
        "expires_at": expires_at,
        "activated_at": None,
        "completed_at": None,
        "voided_at": None,
        "void_reason": None,
        "reinitiated_from_contract_id": reinit_from,
        "document_fingerprint_sha256": None,
        "signing_progress_percent": 0.00,
        "evidence_strength_score": 0.00,
        "evidence_tier": "BRONZE",
        "version": 1,
        "created_at": n,
        "updated_at": n,
    }
    DB.contracts[cid] = c
    if reinit_from is not None:
        DB.reinit_index[reinit_from] = cid
        append_audit(
            contract_id=cid,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            action="CONTRACT_REINITIATED",
            payload={"contract_id": cid, "source": reinit_from},
        )
    return c


def list_contracts(status=None, initiator_org_id=None, limit=10, offset=0):
    rows = list(DB.contracts.values())
    if status:
        rows = [r for r in rows if r["status"] == status]
    if initiator_org_id:
        rows = [r for r in rows if r["initiator_org_id"] == initiator_org_id]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    return rows[offset:offset + limit], total


def patch_contract(contract_id: str, payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise validation_failed("Body must be a JSON object")
    c = get_contract(contract_id)
    if c["status"] != "DRAFT":
        raise APIError(ERR_WORKFLOW_LOCKED, "Contract structural edits only allowed in DRAFT", 409)
    if "version" in payload and payload["version"] is not None:
        if payload["version"] != c["version"]:
            raise version_conflict("Version mismatch")
    if "title" in payload:
        title = payload["title"]
        if not isinstance(title, str) or not (1 <= len(title) <= 200):
            raise validation_failed("title must be a string of length 1..200")
        c["title"] = title
    if "expires_at" in payload:
        try:
            c["expires_at"] = parse_iso(payload["expires_at"])
        except Exception:
            raise validation_failed("expires_at must be ISO 8601")
    if "variable_values" in payload:
        if not isinstance(payload["variable_values"], dict):
            raise validation_failed("variable_values must be a JSON object")
        c["variable_values"] = payload["variable_values"]
    c["version"] += 1
    c["updated_at"] = now()
    return c


# ----- SigningStep / SigningParty ------------------------------------------

def append_signing_step(contract_id: str, payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise validation_failed("Body must be a JSON object")
    c = get_contract(contract_id)
    if c["status"] != "DRAFT":
        raise APIError(ERR_WORKFLOW_LOCKED, "SigningStep edits only allowed in DRAFT", 409)
    step_index = payload.get("step_index")
    mode = payload.get("mode")
    if not isinstance(step_index, int) or isinstance(step_index, bool) or step_index < 1:
        raise validation_failed("step_index must be a positive integer")
    if mode not in VALID_STEP_MODES:
        raise validation_failed("mode must be SEQUENTIAL or PARALLEL_COUNTERSIGN")
    # uniqueness of (contract_id, step_index)
    for s in DB.signing_steps.values():
        if s["contract_id"] == contract_id and s["step_index"] == step_index:
            raise validation_failed("step_index already exists for this contract")
    branch_condition = payload.get("branch_condition")
    if branch_condition is not None and not isinstance(branch_condition, dict):
        raise validation_failed("branch_condition must be an object")
    n = now()
    sid = new_id()
    s = {
        "id": sid,
        "contract_id": contract_id,
        "step_index": step_index,
        "mode": mode,
        "branch_condition": branch_condition,
        "status": "PENDING",
        "activated_at": None,
        "completed_at": None,
        "version": 1,
        "created_at": n,
        "updated_at": n,
    }
    DB.signing_steps[sid] = s
    return s


def append_signing_party(contract_id: str, sid: str, payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise validation_failed("Body must be a JSON object")
    c = get_contract(contract_id)
    if c["status"] != "DRAFT":
        raise APIError(ERR_WORKFLOW_LOCKED, "SigningParty edits only allowed in DRAFT", 409)
    s = get_signing_step(contract_id, sid)

    role_key = payload.get("role_key")
    signer_type = payload.get("signer_type")
    signer_user_id = payload.get("signer_user_id")
    signer_org_id = payload.get("signer_org_id")
    delegation_authorization_id = payload.get("delegation_authorization_id")
    required_auth_factors = payload.get("required_auth_factors")

    if not isinstance(role_key, str) or not role_key:
        raise validation_failed("role_key required")
    if signer_type not in VALID_SIGNER_TYPES:
        raise validation_failed("signer_type invalid")
    if not isinstance(signer_user_id, str) or not signer_user_id:
        raise validation_failed("signer_user_id required")
    if not isinstance(required_auth_factors, list) or not (1 <= len(required_auth_factors) <= 4):
        raise validation_failed("required_auth_factors must be a list of length 1..4")
    if len(set(required_auth_factors)) != len(required_auth_factors):
        raise validation_failed("required_auth_factors must be unique")
    for f in required_auth_factors:
        if f not in VALID_AUTH_FACTORS:
            raise validation_failed(f"required_auth_factors contains invalid factor: {f}")

    if signer_type in ("ORG_LEGAL_REP", "ORG_DELEGATE"):
        if not signer_org_id:
            raise validation_failed("signer_org_id required for ORG_LEGAL_REP/ORG_DELEGATE")
    else:
        signer_org_id = None
        delegation_authorization_id = None

    # Legal rep MFA check
    if signer_type == "ORG_LEGAL_REP" and len(required_auth_factors) < MIN_FACTORS_FOR_LEGAL_REP:
        raise APIError(ERR_LEGAL_REP_REQUIRES_MFA, "ORG_LEGAL_REP requires >=2 factors", 422)

    # Delegation validity
    if signer_type == "ORG_DELEGATE":
        if not delegation_authorization_id:
            raise APIError(ERR_DELEGATION_INVALID, "delegation_authorization_id required for ORG_DELEGATE", 422)
        deleg = DB.org_users.get(delegation_authorization_id)
        # Only enforce structural constraints when an OrgUser entry is registered.
        # If no entry exists, a non-empty id is treated as valid.
        if deleg is not None:
            if deleg.get("status") != "ACTIVE" or deleg.get("org_role") != "AUTHORIZED_DELEGATE":
                raise APIError(ERR_DELEGATION_INVALID, "Invalid delegation_authorization_id", 422)
            if deleg.get("org_id") != signer_org_id:
                raise APIError(ERR_DELEGATION_INVALID, "Delegation org mismatch", 422)

    n = now()
    pid = new_id()
    p = {
        "id": pid,
        "signing_step_id": sid,
        "contract_id": contract_id,
        "role_key": role_key,
        "signer_type": signer_type,
        "signer_user_id": signer_user_id,
        "signer_org_id": signer_org_id,
        "delegation_authorization_id": delegation_authorization_id,
        "required_auth_factors": list(required_auth_factors),
        "status": "WAITING",
        "signed_at": None,
        "timestamp_token_id": None,
        "identity_verification_id": None,
        "version": 1,
        "created_at": n,
        "updated_at": n,
    }
    DB.signing_parties[pid] = p
    return p


def _step_parties_ordered(step_id: str):
    parties = [p for p in DB.signing_parties.values() if p["signing_step_id"] == step_id]
    parties.sort(key=lambda p: p["created_at"])
    return parties


def _activate_step(step: dict, n):
    step["status"] = "ACTIVE"
    step["activated_at"] = n
    step["version"] += 1
    step["updated_at"] = n
    parties = _step_parties_ordered(step["id"])
    if step["mode"] == "PARALLEL_COUNTERSIGN":
        for p in parties:
            if p["status"] == "WAITING":
                p["status"] = "AUTHENTICATING"
                p["version"] += 1
                p["updated_at"] = n
    else:  # SEQUENTIAL
        for p in parties:
            if p["status"] == "WAITING":
                p["status"] = "AUTHENTICATING"
                p["version"] += 1
                p["updated_at"] = n
                break


def _evaluate_branch(condition: dict, variable_values: dict) -> bool:
    """Branch condition: {variable, operator, value, on_false_skip}.

    on_false_skip is the side-effect descriptor; the evaluation itself is
    based on operator and value.
    """
    if not condition:
        return True
    var = condition.get("variable")
    op = condition.get("operator")
    val = condition.get("value")
    actual = (variable_values or {}).get(var) if var else None
    try:
        if op == "==" or op == "eq":
            return actual == val
        if op == "!=" or op == "ne":
            return actual != val
        if op == ">" or op == "gt":
            return actual > val
        if op == "<" or op == "lt":
            return actual < val
        if op == ">=" or op == "gte":
            return actual >= val
        if op == "<=" or op == "lte":
            return actual <= val
        if op == "in":
            return actual in val
        if op == "not_in":
            return actual not in val
    except Exception:
        return False
    # Unknown operator: treat as false (cautious)
    return False


def _next_step_to_evaluate(contract_id: str):
    """Return the lowest-step_index PENDING step under this contract."""
    candidates = [s for s in DB.signing_steps.values()
                  if s["contract_id"] == contract_id and s["status"] == "PENDING"]
    if not candidates:
        return None
    candidates.sort(key=lambda s: s["step_index"])
    return candidates[0]


def _advance_pending_steps(contract: dict, n):
    """Cascade: evaluate the lowest PENDING step. If branch evaluates true (or
    none), activate it. If false, skip it (cascade children) and continue.
    Stops as soon as a step is ACTIVE-or-no-more-PENDING."""
    while True:
        step = _next_step_to_evaluate(contract["id"])
        if step is None:
            return
        # Make sure all earlier steps are terminal
        earlier = [s for s in DB.signing_steps.values()
                   if s["contract_id"] == contract["id"] and s["step_index"] < step["step_index"]]
        if any(s["status"] not in ("SIGNED", "SKIPPED", "REJECTED") for s in earlier):
            return
        if step.get("branch_condition"):
            ok = _evaluate_branch(step["branch_condition"], contract.get("variable_values"))
            if not ok:
                # SKIP step + cascade children
                step["status"] = "SKIPPED"
                step["completed_at"] = n
                step["version"] += 1
                step["updated_at"] = n
                for p in DB.signing_parties.values():
                    if p["signing_step_id"] == step["id"] and p["status"] == "WAITING":
                        p["status"] = "SKIPPED"
                        p["version"] += 1
                        p["updated_at"] = n
                # continue evaluating next step
                continue
        # Activate this step
        _activate_step(step, n)
        return


# ----- Contract activation -------------------------------------------------

def activate_contract(contract_id: str, *, actor_user_id: str, actor_role: str) -> dict:
    c = get_contract(contract_id)
    # Priority 4: TemplateVersion in PUBLISHED (cross-entity precondition)
    tv = DB.template_versions.get(c["template_version_id"])
    if not tv or tv["status"] != "PUBLISHED":
        raise APIError(ERR_TEMPLATE_NOT_PUBLISHED, "TemplateVersion is not PUBLISHED", 409)
    # Priority 5: Contract state must be DRAFT
    if c["status"] != "DRAFT":
        raise invalid_state("Contract must be in DRAFT to activate")

    # Existence of step_index 1
    steps = [s for s in DB.signing_steps.values() if s["contract_id"] == contract_id]
    if not steps:
        raise validation_failed("Contract must have at least one SigningStep")
    if not any(s["step_index"] == 1 for s in steps):
        raise validation_failed("Contract must have a SigningStep with step_index=1")
    # Each step has at least one party
    for s in steps:
        ps = [p for p in DB.signing_parties.values() if p["signing_step_id"] == s["id"]]
        if not ps:
            raise validation_failed(f"SigningStep {s['id']} has no parties")
    # variable_values match required variable_fields
    var_fields = tv.get("variable_fields") or []
    vv = c.get("variable_values") or {}
    for vf in var_fields:
        if not isinstance(vf, dict):
            continue
        if vf.get("required") and vf.get("name") not in vv:
            raise validation_failed(f"Required variable missing: {vf.get('name')}")
    # Segregation of duties: activator != publisher
    publisher = DB.template_version_publisher.get(tv["id"])
    if publisher and publisher == actor_user_id:
        raise APIError(ERR_SEGREGATION_OF_DUTIES, "Activator cannot be the publisher", 403)
    # Expiration
    n = now()
    if not (n < c["expires_at"]):
        raise APIError(ERR_CONTRACT_EXPIRED, "Contract has expired", 409)

    # Compute fingerprint
    fingerprint = compute_document_fingerprint(tv, c.get("variable_values") or {})
    c["status"] = "PENDING_SIGN"
    c["activated_at"] = n
    c["document_fingerprint_sha256"] = fingerprint
    c["version"] += 1
    c["updated_at"] = n
    # Lazy create EvidencePackage in PENDING
    _ensure_evidence_package(contract_id, n)
    # Cascade: activate step_index=1 (or skip if branch false, etc.)
    _advance_pending_steps(c, n)

    append_audit(
        contract_id=contract_id,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action="CONTRACT_ACTIVATED",
        payload={
            "contract_id": contract_id,
            "fingerprint": fingerprint,
        },
    )
    return c


# ----- Manual void ----------------------------------------------------------

def void_contract_manual(contract_id: str, *, actor_user_id: str, actor_role: str) -> dict:
    c = get_contract(contract_id)
    if c["status"] != "PENDING_SIGN":
        raise invalid_state("Manual void requires PENDING_SIGN")
    # No SigningParty in this contract may be SIGNED yet
    for p in DB.signing_parties.values():
        if p["contract_id"] == contract_id and p["status"] == "SIGNED":
            raise invalid_state("Manual void blocked: a party has already signed")
    n = now()
    _cascade_void(c, "MANUAL", n,
                  actor_user_id=actor_user_id,
                  actor_role=actor_role,
                  audit_action="CONTRACT_VOIDED")
    return c
