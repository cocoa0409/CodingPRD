"""Error catalog (SCAFFOLD 1.6 / PRD 5)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super(ApiError, self).__init__(error_id)
        self.error_id = error_id
        spec = CATALOG.get(error_id, (500, "Unexpected error."))
        self.http_status = spec[0]
        self.message = message if message is not None else spec[1]


CATALOG = {
    # --- auth / rbac -------------------------------------------------------
    "ERR_UNAUTHENTICATED": (401, "Authentication headers are required."),
    "ERR_ROLE_NOT_PERMITTED": (403, "Role is not permitted to perform this operation."),
    "ERR_ACTOR_NOT_A_PARTNER": (403, "Acting user is not an eligible partner for this role."),
    "ERR_NOT_RESOURCE_OWNER": (403, "Acting partner does not own this resource."),
    "ERR_BALLOT_CONFIDENTIAL": (403, "Committee deliberation records are confidential."),
    # --- schema -----------------------------------------------------------
    "ERR_INVALID_REQUEST": (422, "Request payload failed validation."),
    # --- not found --------------------------------------------------------
    "ERR_CYCLE_NOT_FOUND": (404, "Compensation cycle not found."),
    "ERR_PARTNER_NOT_FOUND": (404, "Partner not found."),
    "ERR_MATTER_NOT_FOUND": (404, "Matter not found."),
    "ERR_ALLOCATION_NOT_FOUND": (404, "Credit allocation not found."),
    "ERR_RECORD_NOT_FOUND": (404, "Contribution record not found."),
    "ERR_CLAIM_NOT_FOUND": (404, "Credit claim not found."),
    "ERR_ASSESSMENT_NOT_FOUND": (404, "Self-assessment not found."),
    "ERR_REVIEW_NOT_FOUND": (404, "Peer review not found."),
    "ERR_BALLOT_NOT_FOUND": (404, "Committee ballot not found."),
    "ERR_AWARD_NOT_FOUND": (404, "Compensation award not found."),
    "ERR_PAYMENT_NOT_FOUND": (404, "Draw payment not found."),
    "ERR_TRANSITION_NOT_FOUND": (404, "Credit transition not found."),
    # --- uniqueness -------------------------------------------------------
    "ERR_DUPLICATE_CYCLE": (409, "A compensation cycle already exists for that fiscal year."),
    "ERR_DUPLICATE_CLAIM": (409, "This partner has already filed a claim on that matter for this cycle."),
    "ERR_DUPLICATE_ASSESSMENT": (409, "A self-assessment already exists for this partner and cycle."),
    "ERR_DUPLICATE_REVIEW_ASSIGNMENT": (409, "That reviewer is already assigned to this assessment."),
    # --- state preconditions ---------------------------------------------
    "ERR_INVALID_CYCLE_TRANSITION": (409, "That cycle stage transition is not permitted from the current state."),
    "ERR_CLAIM_NOT_IN_DRAFT": (409, "Only a draft claim may be submitted."),
    "ERR_CLAIM_NOT_DISPUTABLE": (409, "Only a submitted claim may be disputed."),
    "ERR_CLAIM_NOT_ADJUDICABLE": (409, "This claim is not adjudicable in its current state."),
    "ERR_ASSESSMENT_NOT_MUTABLE": (409, "Only a draft self-assessment may be submitted."),
    "ERR_ASSESSMENT_NOT_REVIEWABLE": (409, "Only a submitted self-assessment may be accepted or returned."),
    "ERR_REVIEW_ALREADY_DECIDED": (409, "This peer review has already been decided."),
    "ERR_BALLOT_ALREADY_DECIDED": (409, "This ballot has already been decided."),
    "ERR_RECORD_ALREADY_VERIFIED": (409, "This contribution record has already been verified."),
    "ERR_MATTER_NOT_OPEN": (409, "Matter is not in a state that permits this operation."),
    "ERR_AWARD_NOT_DRAWABLE": (409, "Award is not in a state that permits a draw."),
    "ERR_AWARD_NOT_TRUE_UP_READY": (409, "Award is not ready for true-up."),
    "ERR_TRANSITION_NOT_PENDING": (409, "Only a proposed credit transition may be effectuated."),
    "ERR_TRANSITION_NOT_VOIDABLE": (409, "This credit transition cannot be voided."),
    # --- cross-entity state ----------------------------------------------
    "ERR_ASSESSMENT_NOT_ACCEPTED": (409, "The subject partner's self-assessment has not been accepted."),
    "ERR_PARTNER_NOT_DEPARTING": (409, "Partner is not in a departure state that permits this operation."),
    "ERR_SUCCESSOR_NOT_ELIGIBLE": (409, "Named successor is not eligible to receive this credit."),
    # --- concurrency ------------------------------------------------------
    "ERR_STALE_VERSION": (412, "The resource has changed since it was read; re-read and retry."),
    # --- temporal windows -------------------------------------------------
    "ERR_CLAIM_WINDOW_CLOSED": (409, "The origination claim window for this cycle is closed."),
    "ERR_ASSESSMENT_WINDOW_CLOSED": (409, "The self-assessment window for this cycle is closed."),
    "ERR_REVIEW_WINDOW_CLOSED": (409, "The peer review window for this cycle is closed."),
    "ERR_SERVICE_PERIOD_BUFFER_VIOLATION": (
        409,
        "Non-billable service period conflicts with an existing record for this category.",
    ),
    # --- segregation of duties -------------------------------------------
    "ERR_SELF_VOTE_FORBIDDEN": (403, "A committee member may not vote on their own compensation."),
    "ERR_SELF_REVIEW_FORBIDDEN": (403, "A partner may not review their own self-assessment."),
    "ERR_ARBITER_CONFLICT": (403, "Credit arbiter has a conflict of interest in this claim."),
    "ERR_DISPUTER_IS_CLAIMANT": (403, "A partner may not dispute their own origination claim."),
    # --- referential business rules --------------------------------------
    "ERR_CLIENT_NOT_NEW": (409, "Claim basis does not match this client's matter history."),
    # --- interval / cap constraints --------------------------------------
    "ERR_CREDIT_INTERVAL_OVERSUBSCRIBED": (409, "Origination credit on this matter would exceed 100 percent."),
    "ERR_DRAW_PERIOD_ALREADY_PAID": (409, "A draw has already been paid for that period."),
    "ERR_POINTS_CAP_EXCEEDED": (409, "Proposed points exceed the per-ballot cap."),
    # --- aggregate gates --------------------------------------------------
    "ERR_UNRESOLVED_CLAIMS": (409, "Unresolved origination claims remain in this cycle."),
    "ERR_ASSESSMENTS_INCOMPLETE": (409, "Self-assessments are incomplete for this cycle."),
    "ERR_PEER_REVIEWS_INCOMPLETE": (409, "Peer reviews are incomplete."),
    "ERR_QUORUM_NOT_MET": (409, "Committee quorum has not been met for every subject."),
    # --- fiscal closure ---------------------------------------------------
    "ERR_POOL_INSUFFICIENT": (409, "Distributable pool is insufficient to fund committed compensation."),
    "ERR_CYCLE_NOT_REOPENABLE": (409, "This cycle can no longer be reopened for reconsideration."),
    "ERR_AWARDS_NOT_SETTLED": (409, "Every award must be settled before the cycle can close."),
}
