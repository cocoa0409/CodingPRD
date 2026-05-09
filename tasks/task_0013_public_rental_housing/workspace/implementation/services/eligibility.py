"""Cross-check eligibility evaluation (PRD §3.2)."""
from db import db
from services.sync import latest_event


def evaluate_cross_check(application: dict, program: dict) -> tuple[bool, str | None,
                                                                      dict | None]:
    """Run the six-condition cross-check.

    Returns (passed, failing_error_id, tax_event_payload).
    On success: failing_error_id is None and tax_event_payload is the latest
    TAX_INCOME_ASSETS payload (so the caller can persist verified amounts).

    Order of checks (PRD §3.2 — household → identity → income → assets → existing housing).
    """
    members = application.get("household_members") or []
    family_size = max(1, len(members))
    program_id = program["id"]
    application_id = application["id"]

    # 1. Household registration (CIVIL_AFFAIRS_HOUSEHOLD must include every citizen_id)
    civil = latest_event(event_type="CIVIL_AFFAIRS_HOUSEHOLD",
                         subject_id=application_id)
    if civil is None:
        return False, "ERR_HOUSEHOLD_REGISTRATION_MISMATCH", None
    civil_payload = civil.get("payload") or {}
    civil_ids = set()
    # Accept several payload shapes: {citizen_ids: [...]} or
    # {members: [{citizen_id: ...}, ...]} or {household: [{citizen_id: ...}]}
    if isinstance(civil_payload.get("citizen_ids"), list):
        civil_ids = set(civil_payload["citizen_ids"])
    elif isinstance(civil_payload.get("members"), list):
        civil_ids = {m.get("citizen_id") for m in civil_payload["members"]
                     if isinstance(m, dict)}
    elif isinstance(civil_payload.get("household"), list):
        civil_ids = {m.get("citizen_id") for m in civil_payload["household"]
                     if isinstance(m, dict)}
    needed_ids = {m.get("citizen_id") for m in members}
    if not needed_ids.issubset(civil_ids):
        return False, "ERR_HOUSEHOLD_REGISTRATION_MISMATCH", None

    # 2. Identity verification (PUBLIC_SECURITY_IDENTITY must mark every citizen_id verified)
    sec = latest_event(event_type="PUBLIC_SECURITY_IDENTITY",
                       subject_id=application_id)
    if sec is None:
        return False, "ERR_IDENTITY_VERIFICATION_FAILED", None
    sec_payload = sec.get("payload") or {}
    verified_set: set = set()
    # Accept payload shapes: {identities: [{citizen_id, identity_verified}]} or
    # {members: [{citizen_id, identity_verified}]} or {verified: [citizen_ids...]}
    raw_list = (sec_payload.get("identities")
                or sec_payload.get("members")
                or sec_payload.get("verifications")
                or sec_payload.get("citizen_records"))
    if isinstance(raw_list, list):
        for entry in raw_list:
            if isinstance(entry, dict) and entry.get("identity_verified"):
                verified_set.add(entry.get("citizen_id"))
    elif isinstance(sec_payload.get("verified"), list):
        verified_set = set(sec_payload["verified"])
    if not needed_ids.issubset(verified_set):
        return False, "ERR_IDENTITY_VERIFICATION_FAILED", None

    # 3 & 4: Income / asset thresholds (TAX_INCOME_ASSETS)
    tax = latest_event(event_type="TAX_INCOME_ASSETS",
                       subject_id=application_id)
    if tax is None:
        # No tax event → income/asset checks fail closed; report income first
        return False, "ERR_INCOME_OVER_THRESHOLD", None
    tax_payload = tax.get("payload") or {}
    monthly_income = int(tax_payload.get("monthly_income_cents", 0))
    total_assets = int(tax_payload.get("total_assets_cents", 0))

    # PRD: per-capita income/asset, equality passes, strictly greater fails.
    # Multiply both sides to avoid integer division loss:
    #   monthly_income / family_size > program.per_capita_income_threshold
    #   ⇔ monthly_income > program.per_capita_income_threshold * family_size
    income_threshold = int(program.get("per_capita_income_threshold_cents", 0))
    asset_threshold = int(program.get("per_capita_asset_threshold_cents", 0))
    if monthly_income > income_threshold * family_size:
        return False, "ERR_INCOME_OVER_THRESHOLD", None
    if total_assets > asset_threshold * family_size:
        return False, "ERR_ASSETS_OVER_THRESHOLD", None

    # 5. Existing housing detected
    blocked_states = {"ACTIVE", "DEPOSIT_PAID", "SIGNED"}
    member_citizen_ids = needed_ids
    for contract in db.contracts.values():
        if contract.get("status") not in blocked_states:
            continue
        # Walk to parent application to verify program scope
        other_app = db.applications.get(contract.get("application_id"))
        if not other_app or other_app.get("housing_program_id") != program_id:
            continue
        if other_app.get("id") == application_id:
            # Same application's own contract is irrelevant
            continue
        for m in other_app.get("household_members") or []:
            if m.get("citizen_id") in member_citizen_ids:
                return False, "ERR_EXISTING_HOUSING_DETECTED", None

    return True, None, tax_payload
