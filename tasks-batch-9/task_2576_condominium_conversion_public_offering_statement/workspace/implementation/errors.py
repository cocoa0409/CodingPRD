"""The complete error catalogue of PRD section 5 and the ApiError exception."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_CATALOGUE[error_id]
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


ERROR_CATALOGUE = {
    # --- auth ---
    "ERR_MISSING_AUTH_HEADERS": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_IDENTITY_MISMATCH": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # --- existence ---
    "ERR_PROJECT_NOT_FOUND": 404,
    "ERR_ENGINEERING_ARTIFACT_NOT_FOUND": 404,
    "ERR_DECLARATION_ARTIFACT_NOT_FOUND": 404,
    "ERR_DISCLOSURE_ARTIFACT_NOT_FOUND": 404,
    "ERR_TENANT_NOT_FOUND": 404,
    "ERR_FINANCIAL_ARTIFACT_NOT_FOUND": 404,
    "ERR_SALES_ARTIFACT_NOT_FOUND": 404,
    "ERR_CLAIM_NOT_FOUND": 404,
    # --- request shape ---
    "ERR_INVALID_REQUEST": 422,
    "ERR_INVALID_PAGINATION": 422,
    "ERR_DUPLICATE_KEY": 409,
    # --- optimistic concurrency ---
    "ERR_STALE_UNIT_VERSION": 412,
    "ERR_STALE_REPORT_VERSION": 412,
    "ERR_STALE_PROJECT_VERSION": 412,
    "ERR_STALE_BATCH_VERSION": 412,
    # --- posture gates and state ---
    "ERR_PROJECT_FROZEN": 409,
    "ERR_PROJECT_RESTRICTED": 409,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_BATCH_NOT_RELEASED": 409,
    "ERR_POS_NOT_EFFECTIVE": 409,
    "ERR_DECLARATION_NOT_RECORDED": 409,
    "ERR_RESERVE_STUDY_NOT_ADOPTED": 409,
    "ERR_POS_NOT_DELIVERED": 409,
    # --- business safety ---
    "ERR_LIFE_SAFETY_COMPONENT_EXPIRED": 422,
    "ERR_SUITABILITY_GATE_FAILED": 409,
    "ERR_NO_VERIFIED_COMPONENTS": 409,
    "ERR_POS_SECTIONS_INCOMPLETE": 409,
    # --- business temporal ---
    "ERR_NOTICE_PERIOD_NOT_ELAPSED": 409,
    "ERR_ROFR_WINDOW_EXPIRED": 409,
    "ERR_RESCISSION_PERIOD_OPEN": 409,
    "ERR_RESCISSION_PERIOD_CLOSED": 409,
    "ERR_WARRANTY_PERIOD_EXPIRED": 409,
    "ERR_BATCH_WINDOW_OVERLAP": 409,
    "ERR_REMEDIATION_WINDOW_OVERLAP": 409,
    "ERR_REMEDIATION_CAPACITY_EXCEEDED": 409,
    # --- business referential ---
    "ERR_PROJECT_SCOPE_MISMATCH": 409,
    "ERR_ROFR_UNIT_NOT_LINKED": 409,
    "ERR_AGREEMENT_ALREADY_ASSIGNED": 409,
    # --- business constraint ---
    "ERR_PERCENTAGE_INTEREST_NOT_BALANCED": 409,
    "ERR_LAST_INCLUDED_UNIT": 409,
    "ERR_NO_INCLUDED_UNITS": 409,
    "ERR_CLAIM_REOPEN_LIMIT_REACHED": 409,
    # --- business fiscal ---
    "ERR_ESCROW_AMOUNT_MISMATCH": 422,
    "ERR_ESCROW_NOT_FUNDED": 402,
    "ERR_RELOCATION_AMOUNT_MISMATCH": 422,
    "ERR_PRESALE_THRESHOLD_NOT_MET": 409,
}

DEFAULT_MESSAGES = {
    "ERR_MISSING_AUTH_HEADERS": "X-User-ID and X-User-Role headers are required and X-User-Role must name one of the nine declared roles.",
    "ERR_ROLE_NOT_PERMITTED": "The acting role is not permitted to perform this operation.",
    "ERR_IDENTITY_MISMATCH": "The acting identity is not bound to the addressed resource.",
    "ERR_SEGREGATION_OF_DUTIES": "The peer reviewer may not be the engineer who submitted the report.",
    "ERR_PROJECT_NOT_FOUND": "The conversion project could not be found.",
    "ERR_ENGINEERING_ARTIFACT_NOT_FOUND": "The engineering artefact could not be found.",
    "ERR_DECLARATION_ARTIFACT_NOT_FOUND": "The declaration artefact could not be found.",
    "ERR_DISCLOSURE_ARTIFACT_NOT_FOUND": "The disclosure artefact could not be found.",
    "ERR_TENANT_NOT_FOUND": "The tenant household could not be found.",
    "ERR_FINANCIAL_ARTIFACT_NOT_FOUND": "The financial artefact could not be found.",
    "ERR_SALES_ARTIFACT_NOT_FOUND": "The sales artefact could not be found.",
    "ERR_CLAIM_NOT_FOUND": "The warranty claim could not be found.",
    "ERR_INVALID_REQUEST": "The request body is invalid.",
    "ERR_INVALID_PAGINATION": "limit must be an integer in [1, 100] and offset an integer of at least 0.",
    "ERR_DUPLICATE_KEY": "A record with the same natural key already exists.",
    "ERR_STALE_UNIT_VERSION": "expected_unit_version does not match the unit's current version.",
    "ERR_STALE_REPORT_VERSION": "expected_engineering_report_version does not match the report's current version.",
    "ERR_STALE_PROJECT_VERSION": "expected_conversion_project_version does not match the project's current version.",
    "ERR_STALE_BATCH_VERSION": "expected_closing_batch_version does not match the batch's current version.",
    "ERR_PROJECT_FROZEN": "The project's posture is FROZEN and this write is not on the exemption list.",
    "ERR_PROJECT_RESTRICTED": "The project's posture must be OPEN to release a closing batch.",
    "ERR_INVALID_STATE_TRANSITION": "The resource's current state is not a declared source state for this transition.",
    "ERR_BATCH_NOT_RELEASED": "The agreement's assigned closing batch is not RELEASED.",
    "ERR_POS_NOT_EFFECTIVE": "The project has no public offering statement in status EFFECTIVE.",
    "ERR_DECLARATION_NOT_RECORDED": "The project's declaration package is not RECORDED.",
    "ERR_RESERVE_STUDY_NOT_ADOPTED": "The project has no ADOPTED initial budget whose reserve study is ADOPTED.",
    "ERR_POS_NOT_DELIVERED": "The purchase agreement has no pos_delivered_at.",
    "ERR_LIFE_SAFETY_COMPONENT_EXPIRED": "A verified life-safety component has fewer than 5 remaining useful life years.",
    "ERR_SUITABILITY_GATE_FAILED": "The project's suitability_gate is not PASSED.",
    "ERR_NO_VERIFIED_COMPONENTS": "The engineering report has no VERIFIED major component.",
    "ERR_POS_SECTIONS_INCOMPLETE": "Fewer than all nine statutory sections are COMPLETE.",
    "ERR_NOTICE_PERIOD_NOT_ELAPSED": "The household's vacate_deadline_at has not been reached.",
    "ERR_ROFR_WINDOW_EXPIRED": "The right-of-first-refusal window has expired.",
    "ERR_RESCISSION_PERIOD_OPEN": "The rescission period is still open.",
    "ERR_RESCISSION_PERIOD_CLOSED": "The rescission period has closed.",
    "ERR_WARRANTY_PERIOD_EXPIRED": "The common-element warranty period has expired.",
    "ERR_BATCH_WINDOW_OVERLAP": "The closing-batch window is invalid or overlaps a sibling batch window.",
    "ERR_REMEDIATION_WINDOW_OVERLAP": "The remediation window collides with another window on the same component.",
    "ERR_REMEDIATION_CAPACITY_EXCEEDED": "The remediation window exceeds the project's overlapping remediation ceiling.",
    "ERR_PROJECT_SCOPE_MISMATCH": "A referenced record belongs to a different conversion project.",
    "ERR_ROFR_UNIT_NOT_LINKED": "The household is not linked to an INCLUDED unit of the same project.",
    "ERR_AGREEMENT_ALREADY_ASSIGNED": "The purchase agreement is already assigned to a closing batch.",
    "ERR_PERCENTAGE_INTEREST_NOT_BALANCED": "The INCLUDED unit set does not total exactly 10000 basis points.",
    "ERR_LAST_INCLUDED_UNIT": "Withdrawing this unit would leave the package with no INCLUDED unit.",
    "ERR_NO_INCLUDED_UNITS": "The project has no INCLUDED unit, so the presale percentage is undefined.",
    "ERR_CLAIM_REOPEN_LIMIT_REACHED": "The claim has already been reopened the maximum number of times.",
    "ERR_ESCROW_AMOUNT_MISMATCH": "amount_cents must equal the agreement's deposit_cents exactly.",
    "ERR_ESCROW_NOT_FUNDED": "The agreement's escrow_status is not FUNDED.",
    "ERR_RELOCATION_AMOUNT_MISMATCH": "amount_cents must equal the household's relocation_assistance_cents exactly.",
    "ERR_PRESALE_THRESHOLD_NOT_MET": "The batch does not meet both presale threshold clauses.",
}
