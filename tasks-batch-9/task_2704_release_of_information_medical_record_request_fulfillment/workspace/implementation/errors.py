"""Error catalogue (PRD section 5 / scaffold Table 1.6)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        entry = ERRORS.get(error_id)
        self.http_status = http_status or (entry[0] if entry else 400)
        self.message = message or (entry[1] if entry else error_id)


# error_id -> (http_status, default message)
ERRORS = {
    "ERR_UNAUTHENTICATED": (401, "X-User-ID header is required"),
    "ERR_UNAUTHORIZED_ROLE": (403, "Role is not permitted to perform this operation"),
    "ERR_NOT_REQUEST_OWNER": (403, "Requester may only act on its own requests"),
    "ERR_SEGREGATION_OF_DUTIES": (403, "The acting user may not both perform and approve this step"),
    "ERR_INVALID_REQUEST": (400, "Request body failed schema validation"),
    "ERR_INVALID_DATE_RANGE": (400, "Interval endpoints are out of order"),
    "ERR_STATE_FEE_RULE_NOT_FOUND": (404, "State fee rule not found"),
    "ERR_FACILITY_NOT_FOUND": (404, "Facility not found"),
    "ERR_PATIENT_NOT_FOUND": (404, "Patient not found"),
    "ERR_REQUESTER_NOT_FOUND": (404, "Requester not found"),
    "ERR_AUTHORIZATION_NOT_FOUND": (404, "Authorization not found"),
    "ERR_REQUEST_NOT_FOUND": (404, "Request not found"),
    "ERR_SEGMENT_NOT_FOUND": (404, "Record segment not found for this request"),
    "ERR_INVOICE_NOT_FOUND": (404, "Invoice not found"),
    "ERR_DELIVERY_NOT_FOUND": (404, "Delivery not found"),
    "ERR_DENIAL_NOT_FOUND": (404, "Denial decision not found"),
    "ERR_AMENDMENT_NOT_FOUND": (404, "Amendment request not found"),
    "ERR_STALE_REQUEST_VERSION": (412, "Request has changed since it was read"),
    "ERR_STALE_PATIENT_VERSION": (412, "Patient has changed since it was read"),
    "ERR_REQUEST_STATE_INVALID": (409, "Request is not in a state that permits this operation"),
    "ERR_SEGMENT_STATE_INVALID": (409, "Record segment is not in a state that permits this operation"),
    "ERR_AUTHORIZATION_STATE_INVALID": (409, "Authorization is not in a state that permits this operation"),
    "ERR_INVOICE_STATE_INVALID": (409, "Invoice is not in a state that permits this operation"),
    "ERR_DELIVERY_STATE_INVALID": (409, "Delivery is not in a state that permits this operation"),
    "ERR_REVIEW_STATE_INVALID": (409, "Review is not in a state that permits this action"),
    "ERR_FACILITY_SUSPENDED": (409, "Facility is suspended"),
    "ERR_AUTHORIZATION_NOT_VALID": (409, "Governing authorization is not valid"),
    "ERR_AUTHORIZATION_EXPIRED": (409, "Governing authorization has lapsed"),
    "ERR_REQUEST_NOT_RELEASE_READY": (409, "Request has not reached the required fulfillment state"),
    "ERR_PSYCHOTHERAPY_NOTES_NOT_RELEASABLE": (422, "Psychotherapy notes may not be released"),
    "ERR_SENSITIVE_CATEGORY_NOT_AUTHORIZED": (422, "Authorization does not cover this protected category"),
    "ERR_PART2_ACK_MISSING": (422, "Part 2 redisclosure prohibition has not been acknowledged"),
    "ERR_UNENCRYPTED_DELIVERY_NOT_DIRECTED": (422, "Unsecured transmission requires patient direction"),
    "ERR_FAX_NOT_PERMITTED": (422, "Fax may not carry these protected categories"),
    "ERR_RECIPIENT_NOT_DESIGNATED": (422, "Recipient endpoint is not the designated recipient"),
    "ERR_PATIENT_IDENTITY_MISMATCH": (422, "Requester is not the named patient"),
    "ERR_ACCESS_BASIS_REQUESTER_MISMATCH": (422, "Requester type is incompatible with the access basis"),
    "ERR_AUTHORIZATION_REQUIRED": (422, "Access basis and authorization do not agree"),
    "ERR_AMENDMENT_TARGET_NOT_RELEASED": (422, "Amendment target has not been disclosed"),
    "ERR_AUTHORIZATION_WINDOW_OVERLAP": (409, "Overlapping authorization coverage for this patient and requester"),
    "ERR_LEGACY_ARCHIVE_DISABLED": (422, "Legacy archive retrieval is not enabled for this facility"),
    "ERR_LEGACY_WINDOW_CONTENTION": (409, "Legacy gateway window contends with a live job"),
    "ERR_DUPLICATE_MRN": (409, "Medical record number already exists at this facility"),
    "ERR_DUPLICATE_STATE_FEE_RULE": (409, "State fee rule already exists"),
    "ERR_DUPLICATE_INFLIGHT_REQUEST": (409, "An identical request is already in flight"),
    "ERR_EXTENSION_NOT_AVAILABLE": (409, "Statutory extension is not available"),
    "ERR_SEGMENTS_PENDING": (409, "Compilation is incomplete"),
    "ERR_SEGREGATION_REVIEW_INCOMPLETE": (409, "Sensitive review must decide every segregated segment exactly once"),
    "ERR_REDACTION_PAGE_COUNT_INVALID": (422, "Redacted page count exceeds the segment page count"),
    "ERR_REDACTION_NOT_APPROVED": (409, "A redaction is still open on this request"),
    "ERR_DELIVERY_ATTEMPT_LIMIT": (409, "Transmission attempt limit reached"),
    "ERR_DELIVERY_ALREADY_EXISTS": (409, "A live delivery already exists for this request"),
    "ERR_DENIAL_NOT_REVIEWABLE": (422, "This denial ground is not subject to review"),
    "ERR_INVOICE_ALREADY_EXISTS": (409, "This request already has a settled or issued invoice"),
    "ERR_NOTHING_TO_INVOICE": (422, "There is nothing billable on this request"),
    "ERR_PAYMENT_AMOUNT_MISMATCH": (422, "Payment must settle the full amount due"),
    "ERR_INVOICE_UNSETTLED": (402, "Records may not be released before the invoice is settled"),
    "ERR_NOT_FOUND": (404, "Resource not found"),
    "ERR_METHOD_NOT_ALLOWED": (405, "Method not allowed"),
}
