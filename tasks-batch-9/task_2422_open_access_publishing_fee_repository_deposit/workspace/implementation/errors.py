"""Error catalogue (PRD section 5 / scaffold 1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or DEFAULT_MESSAGES.get(error_id, error_id)


DEFAULT_MESSAGES = {
    "ERR_INVALID_REQUEST": "The request body or query string is malformed.",
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required and the role must be recognised.",
    "ERR_UNAUTHORIZED": "The acting role is not authorised for this endpoint.",
    "ERR_NOT_RESOURCE_OWNER": "The acting corresponding author does not own this resource.",
    "ERR_SEGREGATION_OF_DUTIES": "The paying operator must differ from the approving operator.",
    "ERR_PUBLISHER_NOT_FOUND": "Publisher not found.",
    "ERR_JOURNAL_NOT_FOUND": "Journal not found.",
    "ERR_AGREEMENT_NOT_FOUND": "Transformative agreement not found.",
    "ERR_COVERAGE_NOT_FOUND": "Agreement coverage not found.",
    "ERR_AUTHOR_NOT_FOUND": "Author not found.",
    "ERR_FUNDER_NOT_FOUND": "Funder not found.",
    "ERR_GRANT_NOT_FOUND": "Grant not found.",
    "ERR_FUND_NOT_FOUND": "APC fund not found.",
    "ERR_ARTICLE_NOT_FOUND": "Article not found.",
    "ERR_DETERMINATION_NOT_FOUND": "Eligibility determination not found.",
    "ERR_FUND_REQUEST_NOT_FOUND": "Fund request not found.",
    "ERR_INVOICE_NOT_FOUND": "Publisher invoice not found.",
    "ERR_DEPOSIT_NOT_FOUND": "Repository deposit not found.",
    "ERR_STALE_PARENT_VERSION": "The supplied parent version does not match the current version.",
    "ERR_AGREEMENT_NOT_ACTIVATABLE": "The agreement cannot be activated in its current state.",
    "ERR_REQUEST_NOT_REVIEWABLE": "The fund request status does not permit this operation.",
    "ERR_REQUEST_NOT_RESUBMITTABLE": "The fund request is not awaiting further information.",
    "ERR_DEPOSIT_INVALID_STATE": "The deposit status does not permit this operation.",
    "ERR_INVOICE_INVALID_STATE": "The invoice status does not permit this operation.",
    "ERR_ARTICLE_ALREADY_PUBLISHED": "The article already has a publication date.",
    "ERR_FUND_FROZEN": "The fund is already frozen.",
    "ERR_PUBLISHER_BLOCKED": "The publisher of this journal is blocked by predatory screening.",
    "ERR_LICENSE_NOT_PERMITTED": "The deposit license does not satisfy the funder's requirement.",
    "ERR_ORCID_REQUIRED": "The corresponding author has no ORCID iD for profile linkage.",
    "ERR_GRANT_NOT_ACTIVE": "The referenced grant is not active for this operation.",
    "ERR_ELIGIBILITY_NOT_DETERMINED": "No effective eligibility determination permits this operation.",
    "ERR_COVERAGE_JOURNAL_PUBLISHER_MISMATCH": "The journal does not belong to the agreement's publisher.",
    "ERR_ARTICLE_NOT_FUNDED": "The article's funding status does not permit payment approval.",
    "ERR_APPOINTMENT_WINDOW_EXPIRED": "accepted_on falls outside the author's appointment window.",
    "ERR_AGREEMENT_WINDOW_OVERLAP": "The agreement window overlaps another agreement of this publisher.",
    "ERR_COVERAGE_WINDOW_CONFLICT": "The coverage window conflicts with another coverage line for this journal.",
    "ERR_DEPOSIT_VERSION_CONFLICT": "Another deposit of this article is still open.",
    "ERR_DUPLICATE_ISSN": "The ISSN is already registered.",
    "ERR_DUPLICATE_AGREEMENT_CODE": "The agreement code is already registered.",
    "ERR_DUPLICATE_ORCID": "The ORCID iD is already registered.",
    "ERR_DUPLICATE_INVOICE_NUMBER": "The invoice number is already used by this publisher.",
    "ERR_DUPLICATE_FUND_PRIORITY": "Another fund in this fiscal year already holds this priority rank.",
    "ERR_DUPLICATE_CODE": "The code is already registered.",
    "ERR_REQUEST_EXCEEDS_ELIGIBLE": "requested_cents exceeds the eligible request ceiling.",
    "ERR_AUTHOR_CAP_EXHAUSTED": "The author's remaining annual allowance is exhausted.",
    "ERR_NO_FUND_CAPACITY": "No eligible open fund can contribute to this request.",
}
