"""Error catalogue (PRD section 5 / SCAFFOLD errors table)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, status=None):
        super().__init__(error_id)
        self.error_id = error_id
        spec = CATALOG.get(error_id, (400, "Request failed."))
        self.status = status if status is not None else spec[0]
        self.message = message if message is not None else spec[1]


def fail(error_id, message=None):
    raise ApiError(error_id, message)


CATALOG = {
    # auth / rbac
    "ERR_UNAUTHENTICATED": (401, "Missing or unknown X-Role header."),
    "ERR_UNAUTHORIZED": (403, "Role not permitted for this endpoint."),
    "ERR_ACTION_ROLE_MISMATCH": (403, "Action not permitted for the caller's role."),
    "ERR_SEGREGATION_OF_DUTIES": (403, "The closing manager may not be the valuation approver."),
    "ERR_NOT_DEAL_LANDOWNER": (403, "Caller is not the landowner of this lease stream."),
    "ERR_NOT_ROFR_HOLDER": (403, "Caller is not the tower company holding this right of first refusal."),
    # schema
    "ERR_INVALID_REQUEST": (400, "Request body failed validation."),
    # existence
    "ERR_PORTFOLIO_NOT_FOUND": (404, "Portfolio not found."),
    "ERR_FACILITY_NOT_FOUND": (404, "Financing facility not found."),
    "ERR_TOWER_COMPANY_NOT_FOUND": (404, "Tower company not found."),
    "ERR_TOWER_SITE_NOT_FOUND": (404, "Tower site not found."),
    "ERR_LANDOWNER_NOT_FOUND": (404, "Landowner not found."),
    "ERR_LEASE_STREAM_NOT_FOUND": (404, "Lease stream not found."),
    "ERR_TENANCY_NOT_FOUND": (404, "Carrier tenancy not found."),
    "ERR_VALUATION_NOT_FOUND": (404, "Stream valuation not found."),
    "ERR_DEAL_NOT_FOUND": (404, "Deal not found."),
    "ERR_OFFER_NOT_FOUND": (404, "Offer not found."),
    "ERR_TITLE_REPORT_NOT_FOUND": (404, "Title report not found."),
    "ERR_ROFR_NOTICE_NOT_FOUND": (404, "ROFR notice not found."),
    "ERR_DISPUTE_NOT_FOUND": (404, "Dispute case not found."),
    "ERR_PLEDGE_NOT_FOUND": (404, "Collateral pledge not found."),
    "ERR_AMENDMENT_NOT_FOUND": (404, "Amendment event not found."),
    "ERR_NOT_FOUND": (404, "Resource not found."),
    # concurrency
    "ERR_STALE_LEASE_STREAM_VERSION": (
        412, "expected_lease_stream_version does not match the lease stream's current version."),
    "ERR_STALE_FACILITY_VERSION": (
        412, "expected_facility_version does not match the facility's current version."),
    # state
    "ERR_INVALID_OFFER_STATE": (409, "Offer is not in a state that allows this action."),
    "ERR_OFFER_EXPIRED": (409, "Offer has expired."),
    "ERR_INVALID_DEAL_STAGE": (409, "Deal stage does not allow this operation."),
    "ERR_INVALID_CAPITAL_STATE": (409, "Deal capital state does not allow this operation."),
    "ERR_INVALID_TITLE_STATE": (409, "Title report is not in a state that allows this action."),
    "ERR_INVALID_DISPUTE_STATE": (409, "Dispute case is not in a state that allows this action."),
    "ERR_INVALID_ROFR_STATE": (409, "ROFR notice is not open for a response."),
    "ERR_INVALID_PLEDGE_STATE": (409, "Collateral pledge is not in a state that allows this action."),
    "ERR_INVALID_AMENDMENT_STATE": (409, "Amendment event is not in a state that allows this action."),
    "ERR_VALUATION_NOT_APPROVED": (409, "The pinned valuation is not approved."),
    "ERR_VALUATION_STALE": (409, "The pinned valuation is stale or superseded."),
    # business safety / referential
    "ERR_LANDOWNER_DO_NOT_CONTACT": (422, "Landowner has been marked do-not-contact."),
    "ERR_ROFR_WINDOW_OPEN": (422, "The right-of-first-refusal window is still open."),
    "ERR_OPEN_DISPUTE_BLOCKS_CLOSE": (422, "An unresolved landowner dispute blocks closing."),
    "ERR_MORTGAGE_CONSENT_MISSING": (422, "Mortgagee consent has not been granted."),
    "ERR_TITLE_EXCEPTIONS_OPEN": (422, "Title exceptions remain open."),
    # business constraints
    "ERR_MORTGAGE_CONSENT_NOT_REQUIRED": (422, "No mortgage is of record; consent is not applicable."),
    "ERR_VALUATION_METHOD_MISMATCH": (422, "Offer type does not match the pinned valuation method."),
    "ERR_NO_ACTIVE_TENANCY": (422, "The lease stream has no active carrier tenancy."),
    "ERR_STREAM_NOT_ACQUIRED": (422, "The lease stream has not been acquired."),
    "ERR_DUPLICATE_ACTIVE_DEAL": (422, "Another active deal already exists for this lease stream."),
    "ERR_OFFER_ALREADY_OUTSTANDING": (422, "An offer is already outstanding on this deal."),
    "ERR_NEGOTIATION_ROUNDS_EXHAUSTED": (422, "The maximum number of negotiation rounds has been used."),
    "ERR_CURE_ATTEMPTS_EXHAUSTED": (422, "The maximum number of cure attempts has been used."),
    "ERR_DISPUTE_ALREADY_OPEN": (
        422, "An unresolved dispute of this type already exists for the lease stream."),
    # temporal
    "ERR_ROFR_WINDOW_OVERLAP": (422, "Another ROFR notice window is still running on this deal."),
    "ERR_PLEDGE_PERIOD_OVERLAP": (
        422, "Pledge period overlaps or abuts an existing pledge on this lease stream."),
    # fiscal
    "ERR_OFFER_EXCEEDS_GUARDRAIL": (422, "Offer amount exceeds the valuation's maximum bid."),
    "ERR_PORTFOLIO_CAPITAL_FROZEN": (422, "Portfolio capital posture is frozen."),
    "ERR_INSUFFICIENT_PORTFOLIO_CAPITAL": (
        402, "Portfolio available capital is insufficient for this commitment."),
    "ERR_CAPITAL_WITHDRAWAL_EXCEEDS_AVAILABLE": (422, "Capital withdrawal exceeds available capital."),
    "ERR_BORROWING_BASE_DEFICIT": (422, "The release would leave advances above the borrowing base."),
    "ERR_ADVANCE_EXCEEDS_BORROWING_BASE": (402, "Requested advance exceeds the facility borrowing base."),
}
