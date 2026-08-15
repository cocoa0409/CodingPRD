"""Error types and the error catalog from the scaffold."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


ERRORS = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": (400, "X-User-ID or X-User-Role header missing or malformed"),
    "ERR_INSUFFICIENT_PERMISSIONS": (403, "Role not authorized for this endpoint"),
    "ERR_ASSET_NOT_FOUND": (404, "RightsAsset id not found"),
    "ERR_BROADCASTER_NOT_FOUND": (404, "Broadcaster id not found"),
    "ERR_PACKAGE_NOT_FOUND": (404, "RightsPackage id not found"),
    "ERR_BID_NOT_FOUND": (404, "Bid id not found"),
    "ERR_DEAL_NOT_FOUND": (404, "Deal id not found"),
    "ERR_MILESTONE_NOT_FOUND": (404, "PaymentMilestone id not found"),
    "ERR_OBLIGATION_NOT_FOUND": (404, "ProductionObligation id not found"),
    "ERR_EVENT_NOT_FOUND": (404, "BroadcastEvent id not found"),
    "ERR_MEASUREMENT_NOT_FOUND": (404, "AudienceMeasurement id not found"),
    "ERR_SUBLICENSE_NOT_FOUND": (404, "SublicenseRequest id not found"),
    "ERR_BLACKOUT_NOT_FOUND": (404, "BlackoutWindow id not found"),
    "ERR_RENEWAL_OFFER_NOT_FOUND": (404, "RenewalOffer id not found"),
    "ERR_RIGHTS_CONFLICT_NOT_FOUND": (404, "RightsConflict id not found"),
    "ERR_ASSET_NOT_OPEN": (409, "lock-packages requires asset OPEN"),
    "ERR_ASSET_NOT_LOCKED": (409, "close-awards requires asset PACKAGES_LOCKED"),
    "ERR_ASSET_NOT_AWARD_CLOSED": (409, "retire requires asset AWARD_CLOSED"),
    "ERR_PACKAGE_DEFINITION_INVALID": (422, "Package field validation failed at lock-packages time"),
    "ERR_PACKAGE_NOT_NEGOTIATING": (409, "Accept requires package UNDER_NEGOTIATION"),
    "ERR_PACKAGE_NOT_ACCEPTING_BIDS": (409, "Bid submit requires package OPEN_FOR_BIDS or UNDER_NEGOTIATION"),
    "ERR_PACKAGE_NOT_WITHDRAWABLE": (409, "Withdraw requires OPEN_FOR_BIDS or UNDER_NEGOTIATION"),
    "ERR_PACKAGE_ALREADY_AWARDED": (409, "Another bid has already been accepted on this package"),
    "ERR_UNRESOLVED_PACKAGES_EXIST": (409, "close-awards requires every package AWARDED or WITHDRAWN"),
    "ERR_BROADCASTER_NOT_REGISTERED": (409, "Accredit requires REGISTERED"),
    "ERR_BROADCASTER_UNRATED": (422, "Accreditation requires credit_rating != UNRATED"),
    "ERR_BROADCASTER_NOT_ACCREDITED": (409, "Action requires broadcaster ACCREDITED"),
    "ERR_BROADCASTER_NOT_SUSPENDED": (409, "Reinstate or bar requires broadcaster SUSPENDED"),
    "ERR_NO_BREACH_DEAL": (422, "Bar requires at least one TERMINATED_BREACH deal for this broadcaster"),
    "ERR_BID_NOT_DRAFT": (409, "Submit requires bid DRAFT"),
    "ERR_BID_NOT_SUBMITTED": (409, "start-review requires bid SUBMITTED"),
    "ERR_BID_NOT_UNDER_REVIEW": (409, "shortlist requires bid UNDER_REVIEW"),
    "ERR_BID_NOT_SHORTLISTED": (409, "counter or accept requires bid SHORTLISTED"),
    "ERR_BID_NOT_REJECTABLE": (409, "reject requires bid in UNDER_REVIEW, SHORTLISTED, or COUNTERED"),
    "ERR_BID_NOT_WITHDRAWABLE": (409, "withdraw requires bid in DRAFT, SUBMITTED, UNDER_REVIEW, SHORTLISTED, or COUNTERED"),
    "ERR_DEAL_NOT_DRAFT": (409, "Execute requires deal DRAFT"),
    "ERR_DEAL_NOT_LIVE": (409, "Milestone invoice requires deal EXECUTED or ACTIVE"),
    "ERR_DEAL_NOT_ACTIVE": (409, "Action requires deal ACTIVE"),
    "ERR_DEAL_FROZEN": (409, "Action requires deal.posture != FROZEN"),
    "ERR_DEALS_STILL_ACTIVE": (409, "Asset retire requires all deals terminal"),
    "ERR_INVALID_TERM": (422, "Deal term invalid (term_start >= term_end)"),
    "ERR_NO_PAYMENT_SCHEDULE": (422, "Execute requires at least one PaymentMilestone"),
    "ERR_NO_PRODUCTION_OBLIGATION": (422, "Execute requires at least one ProductionObligation"),
    "ERR_UNRESOLVED_RIGHTS_CONFLICT": (409, "Execute blocked by unresolved RightsConflict rows"),
    "ERR_MILESTONE_NOT_SCHEDULED": (409, "Invoice requires milestone SCHEDULED"),
    "ERR_OBLIGATION_NOT_TRACKING": (409, "Mark-delivered requires obligation TRACKING"),
    "ERR_EVENT_NOT_DELIVERED": (409, "Confirm measurement requires event DELIVERED"),
    "ERR_NO_SHORTFALL": (422, "Declare-shortfall requires games_delivered < games_required"),
    "ERR_RENEWAL_WINDOW_NOT_OPEN": (409, "Open-renewal requires clock within renewal window"),
    "ERR_DEAL_ALREADY_EXPIRED": (409, "Open-renewal requires clock < term_end"),
    "ERR_MATCHING_WINDOW_EXPIRED": (409, "Match requires clock <= matching_window_end"),
    "ERR_MATCHING_WINDOW_ACTIVE": (409, "Exercise of third-party offer requires MATCHED status or expired matching window"),
    "ERR_DEFAULT_GRACE_NOT_ELAPSED": (409, "Declare-default requires clock >= due_date + DEFAULT_GRACE_DAYS"),
    "ERR_REVOKE_CONDITION_NOT_MET": (409, "Revoke requires termination or covering blackout"),
    "ERR_BID_BELOW_FLOOR": (422, "offered_fee_cents < package.minimum_bid_cents"),
    "ERR_COMMITMENT_BELOW_PACKAGE": (422, "production_commitment_games < package.games_committed"),
    "ERR_BIDDER_NOT_GRADE_FOR_BROADER": (422, "exclusivity_request == BROADER requires INVESTMENT_GRADE credit_rating"),
    "ERR_BLACKOUT_VIOLATION": (409, "Sublicense window intersects blackout window"),
    "ERR_SUBLICENSE_WINDOW_OUTSIDE_PACKAGE": (422, "Sublicense window not strict subset of parent package window"),
    "ERR_SUBLICENSE_OVERLAP": (409, "Another APPROVED sublicense overlaps (territory, platform, window)"),
    "ERR_OUTSTANDING_DELINQUENCY": (409, "Terminate-convenience requires zero overdue milestones"),
    "ERR_BREACH_CONDITION_NOT_MET": (409, "Terminate-breach requires payment_delinquency_count >= BREACH_THRESHOLD or posture FROZEN"),
    "ERR_INVALID_REQUEST": (400, "Generic request validation failure"),
    "ERR_STALE_DEAL_VERSION": (412, "expected_deal_version does not match current Deal.version"),
    "ERR_STALE_PACKAGE_VERSION": (412, "expected_package_version does not match current RightsPackage.version"),
}


def raise_error(error_id, message=None):
    http_status, default_msg = ERRORS[error_id]
    raise ApiError(error_id, http_status, message or default_msg)
