"""Error catalog for the Manufactured Home Transport & Set API (PRD section 5)."""


class ApiError(Exception):
    """Raised anywhere in a request to abort with one envelope error."""

    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)
        self.message = message or DEFAULT_MESSAGES.get(
            error_id, "The request could not be completed."
        )


ERROR_HTTP = {
    # --- auth / shape ---
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    # --- existence ---
    "ERR_PLANT_NOT_FOUND": 404,
    "ERR_HAULER_NOT_FOUND": 404,
    "ERR_ESCORT_CREW_NOT_FOUND": 404,
    "ERR_SET_CREW_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_SECTION_NOT_FOUND": 404,
    "ERR_SITE_NOT_FOUND": 404,
    "ERR_PERMIT_NOT_FOUND": 404,
    "ERR_ROUTE_LEG_NOT_FOUND": 404,
    "ERR_ESCORT_ASSIGNMENT_NOT_FOUND": 404,
    "ERR_SET_JOB_NOT_FOUND": 404,
    "ERR_MARRIAGE_JOINT_NOT_FOUND": 404,
    "ERR_ANCHOR_CERT_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    # --- optimistic concurrency ---
    "ERR_STALE_ORDER_VERSION": 412,
    "ERR_STALE_SECTION_VERSION": 412,
    # --- cross-entity state gates ---
    "ERR_SITE_NOT_READY": 409,
    "ERR_ORDER_POSTURE_BLOCKED": 409,
    "ERR_SECTIONS_NOT_DELIVERED": 422,
    "ERR_SECTION_COUNT_MISMATCH": 422,
    # --- safety / qualification ---
    "ERR_INSTALLER_LICENSE_INVALID": 422,
    "ERR_ESCORT_ENDORSEMENT_MISSING": 422,
    "ERR_ESCORT_CREW_OVERBOOKED": 422,
    "ERR_HAULER_SUSPENDED": 422,
    "ERR_SEGREGATION_OF_DUTIES": 422,
    # --- referential coherence ---
    "ERR_LEG_PERMIT_MISMATCH": 422,
    "ERR_SECTION_MATE_INVALID": 422,
    # --- workflow completeness gates ---
    "ERR_ANCHOR_NOT_CERTIFIED": 422,
    "ERR_MARRIAGE_LINE_NOT_CLOSED": 422,
    "ERR_SCOPE_SPLIT_INCOMPLETE": 422,
    "ERR_UTILITY_CROSSOVER_INCOMPLETE": 422,
    "ERR_MARRIAGE_JOINT_COUNT_MISMATCH": 422,
    "ERR_PERMIT_ESCORT_SHORTFALL": 422,
    "ERR_ANCHOR_REVISION_LIMIT": 422,
    "ERR_ANCHOR_COMPLIANCE_FAILED": 422,
    # --- temporal / capacity ---
    "ERR_INVALID_WINDOW": 422,
    "ERR_ESCORT_WINDOW_CONFLICT": 409,
    "ERR_SET_CREW_CAPACITY_EXCEEDED": 409,
    # --- uniqueness ---
    "ERR_DUPLICATE_SECTION_INDEX": 409,
    "ERR_DUPLICATE_LEG_SEQUENCE": 409,
    "ERR_DUPLICATE_JOINT_INDEX": 409,
    "ERR_DUPLICATE_ANCHOR_CERT": 409,
    # --- fiscal ---
    "ERR_PERMIT_FEE_UNPAID": 402,
    "ERR_CLAIM_AMOUNT_EXCEEDS_CAP": 422,
    "ERR_CLAIM_EVIDENCE_MISSING": 422,
    "ERR_CLAIM_STAGE_MISMATCH": 422,
    # --- transport-level fallbacks (never part of the catalog contract) ---
    "ERR_NOT_FOUND": 404,
    "ERR_METHOD_NOT_ALLOWED": 405,
    "ERR_INTERNAL": 500,
}

DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required.",
    "ERR_UNAUTHORIZED": "The acting role is not authorized for this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The acting principal does not own the addressed resource.",
    "ERR_INVALID_REQUEST": "The request body or query string failed schema validation.",
    "ERR_INVALID_STATE": "The addressed resource's current state does not permit this transition.",
    "ERR_PLANT_NOT_FOUND": "Plant not found.",
    "ERR_HAULER_NOT_FOUND": "Hauler not found.",
    "ERR_ESCORT_CREW_NOT_FOUND": "Escort crew not found.",
    "ERR_SET_CREW_NOT_FOUND": "Set crew not found.",
    "ERR_ORDER_NOT_FOUND": "Installation order not found.",
    "ERR_SECTION_NOT_FOUND": "Home section not found.",
    "ERR_SITE_NOT_FOUND": "Site not found.",
    "ERR_PERMIT_NOT_FOUND": "Transport permit not found.",
    "ERR_ROUTE_LEG_NOT_FOUND": "Route leg not found.",
    "ERR_ESCORT_ASSIGNMENT_NOT_FOUND": "Escort assignment not found.",
    "ERR_SET_JOB_NOT_FOUND": "Set job not found.",
    "ERR_MARRIAGE_JOINT_NOT_FOUND": "Marriage joint not found.",
    "ERR_ANCHOR_CERT_NOT_FOUND": "Anchor certification not found.",
    "ERR_CLAIM_NOT_FOUND": "Damage claim not found.",
    "ERR_STALE_ORDER_VERSION": "expected_order_version does not match the order's current version.",
    "ERR_STALE_SECTION_VERSION": "expected_section_version does not match the section's current version.",
    "ERR_SITE_NOT_READY": "The order's site has not passed readiness inspection.",
    "ERR_ORDER_POSTURE_BLOCKED": "The order's posture blocks this operation.",
    "ERR_SECTIONS_NOT_DELIVERED": "Not every home section of the order has been delivered.",
    "ERR_SECTION_COUNT_MISMATCH": "The number of home sections does not match the order's section_count.",
    "ERR_INSTALLER_LICENSE_INVALID": "The installer crew's licence is not valid.",
    "ERR_ESCORT_ENDORSEMENT_MISSING": "The escort crew's endorsement does not cover the permit class.",
    "ERR_ESCORT_CREW_OVERBOOKED": "The escort crew is overbooked.",
    "ERR_HAULER_SUSPENDED": "The hauler is suspended.",
    "ERR_SEGREGATION_OF_DUTIES": "The site-readiness inspector may not sign the final inspection.",
    "ERR_LEG_PERMIT_MISMATCH": "The leg's state_code differs from its permit's state_code.",
    "ERR_SECTION_MATE_INVALID": "mates_to_section_id is not a valid marriage-line partner.",
    "ERR_ANCHOR_NOT_CERTIFIED": "No CERTIFIED anchor certification exists for this set job.",
    "ERR_MARRIAGE_LINE_NOT_CLOSED": "The marriage line is not closed with a passing verdict.",
    "ERR_SCOPE_SPLIT_INCOMPLETE": "The skirting/steps scope split has not been recorded.",
    "ERR_UTILITY_CROSSOVER_INCOMPLETE": "The utility crossover has not been recorded.",
    "ERR_MARRIAGE_JOINT_COUNT_MISMATCH": "The recorded marriage-joint count is wrong for this order.",
    "ERR_PERMIT_ESCORT_SHORTFALL": "Reserved escort coverage is short of what the permit requires.",
    "ERR_ANCHOR_REVISION_LIMIT": "The anchor certification revision ceiling has been reached.",
    "ERR_ANCHOR_COMPLIANCE_FAILED": "The anchoring package does not satisfy HUD and state standards.",
    "ERR_INVALID_WINDOW": "The supplied interval is not well formed.",
    "ERR_ESCORT_WINDOW_CONFLICT": "The requested escort window conflicts with an existing reservation.",
    "ERR_SET_CREW_CAPACITY_EXCEEDED": "The set crew's per-day capacity would be exceeded.",
    "ERR_DUPLICATE_SECTION_INDEX": "That section_index already exists on this order.",
    "ERR_DUPLICATE_LEG_SEQUENCE": "That sequence_no already exists on this permit.",
    "ERR_DUPLICATE_JOINT_INDEX": "That joint_index already exists on this set job.",
    "ERR_DUPLICATE_ANCHOR_CERT": "A non-FAILED anchor certification already exists for this set job.",
    "ERR_PERMIT_FEE_UNPAID": "The permit's paid amount is below the final assessed fee.",
    "ERR_CLAIM_AMOUNT_EXCEEDS_CAP": "claimed_amount_cents exceeds the single-claim ceiling.",
    "ERR_CLAIM_EVIDENCE_MISSING": "The evidence points must sum to at least 1.",
    "ERR_CLAIM_STAGE_MISMATCH": "The claim's discovered_stage has no owning party.",
    "ERR_NOT_FOUND": "Resource not found.",
    "ERR_METHOD_NOT_ALLOWED": "Method not allowed for this path.",
    "ERR_INTERNAL": "Internal server error.",
}


def fail(error_id, message=None):
    raise ApiError(error_id, message)


def message_for(error_id):
    return DEFAULT_MESSAGES.get(error_id, "The request could not be completed.")
