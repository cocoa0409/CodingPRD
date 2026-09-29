"""Error catalogue (PRD section 5) and the API exception type."""

# error_id -> (http_status, default human message)
ERRORS = {
    # --- 400 ---
    "ERR_VALIDATION": (400, "A required field is missing, malformed, out of range, or violates an enum or numeric domain."),
    # --- 403 ---
    "ERR_UNAUTHORIZED": (403, "The caller's identity header is missing or the caller's role is not permitted to invoke this endpoint."),
    "ERR_NOT_PROPOSAL_OWNER": (403, "Only the proposal's author may perform this operation."),
    "ERR_NOT_BOARD_OPERATOR": (403, "Only the airing's board operator may perform this operation."),
    "ERR_NOT_COMMITTEE_MEMBER": (403, "The caller does not hold a committee seat."),
    "ERR_SELF_VOTE_FORBIDDEN": (403, "A proposer may not vote on their own proposal."),
    "ERR_SEGREGATION_OF_DUTIES": (403, "The user who reviewed the underwriting copy may not adjudicate an incident naming that spot."),
    # --- 404 ---
    "ERR_VOLUNTEER_NOT_FOUND": (404, "Volunteer not found."),
    "ERR_CERTIFICATION_NOT_FOUND": (404, "Certification record not found."),
    "ERR_PROPOSAL_NOT_FOUND": (404, "Program proposal not found."),
    "ERR_VOTE_NOT_FOUND": (404, "Committee vote not found."),
    "ERR_PROGRAM_NOT_FOUND": (404, "Program not found."),
    "ERR_GRID_NOT_FOUND": (404, "Schedule grid not found."),
    "ERR_SLOT_NOT_FOUND": (404, "Slot assignment not found."),
    "ERR_EPISODE_NOT_FOUND": (404, "Episode not found."),
    "ERR_PLAYLIST_ENTRY_NOT_FOUND": (404, "Playlist entry not found."),
    "ERR_SPOT_NOT_FOUND": (404, "Underwriting spot not found."),
    "ERR_INCIDENT_NOT_FOUND": (404, "Compliance incident not found."),
    "ERR_DRIVE_NOT_FOUND": (404, "Membership drive not found."),
    "ERR_SHIFT_NOT_FOUND": (404, "Phone bank shift not found."),
    "ERR_PREMIUM_NOT_FOUND": (404, "Premium item not found."),
    "ERR_PLEDGE_NOT_FOUND": (404, "Pledge not found."),
    # --- 409 ---
    "ERR_DUPLICATE_KEY": (409, "A record with that unique key already exists."),
    "ERR_DUPLICATE_VOTE": (409, "That committee member has already voted in this review round."),
    "ERR_PROGRAM_ALREADY_EXISTS": (409, "That proposal has already produced a program."),
    "ERR_INVALID_STATE": (409, "The record is not in a state that permits this transition."),
    "ERR_GRID_NOT_MUTABLE": (409, "The schedule grid is published or superseded and can no longer be edited."),
    "ERR_SLOT_CONFLICT": (409, "The requested airtime collides with an existing occupation on the same grid and day."),
    "ERR_SENIORITY_MARGIN_UNMET": (409, "The challenger's seniority score does not exceed the incumbent's by the required margin."),
    "ERR_TENTATIVE_SLOTS_PRESENT": (409, "The grid still holds tentative occupations."),
    "ERR_PROGRAM_RESTRICTED": (409, "The program's compliance standing is RESTRICTED."),
    "ERR_PROPOSAL_NOT_IN_REVIEW": (409, "The proposal is not in committee review."),
    "ERR_LOG_NOT_PENDING": (409, "The music log is not pending."),
    "ERR_PUBLIC_FILE_NOT_REQUIRED": (409, "No public-file obligation is outstanding for that spot."),
    "ERR_RETAKE_TOO_SOON": (409, "The retake cooling-off window has not elapsed."),
    "ERR_MAX_ATTEMPTS_REACHED": (409, "The maximum number of examination attempts has been reached."),
    "ERR_DRIVE_NOT_ACTIVE": (409, "The membership drive is not active."),
    "ERR_PLEDGES_PENDING": (409, "The drive still holds pledges awaiting settlement."),
    "ERR_SHIFT_CONFLICT": (409, "The volunteer already holds an overlapping phone bank shift."),
    "ERR_PHONE_LINE_CAPACITY": (409, "The drive has no free phone line for that interval."),
    "ERR_PREMIUM_NOT_RESERVED": (409, "The pledge holds no reserved premium."),
    "ERR_PLEDGE_NOT_PAID": (409, "The pledge has not been paid."),
    "ERR_PREMIUM_OUT_OF_STOCK": (409, "The premium item has no units on hand."),
    "ERR_NOT_EDITABLE": (409, "The record is no longer editable."),
    # --- 412 ---
    "ERR_STALE_GRID_VERSION": (412, "The supplied expected_grid_version does not match the grid's current version."),
    "ERR_STALE_PROPOSAL_VERSION": (412, "The supplied expected_proposal_version does not match the proposal's current version."),
    "ERR_STALE_PROGRAM_VERSION": (412, "The supplied expected_program_version does not match the program's current version."),
    # --- 422 ---
    "ERR_INVALID_INTERVAL": (422, "The interval's end must fall strictly after its start."),
    "ERR_SLOT_PROGRAM_MISMATCH": (422, "The slot assignment does not belong to the named program."),
    "ERR_EPISODE_SLOT_MISMATCH": (422, "The scheduled start does not line up with the slot's day and start minute."),
    "ERR_SHIFT_DRIVE_MISMATCH": (422, "The shift does not belong to the named drive."),
    "ERR_INCIDENT_TARGET_REQUIRED": (422, "The incident category requires a target that was not supplied."),
    "ERR_REVOCATION_UNSUPPORTED": (422, "The named incident does not support revoking this certification."),
    "ERR_PROPOSER_NOT_CERTIFIED": (422, "The proposer is not certified."),
    "ERR_VOTER_INELIGIBLE": (422, "The committee member is suspended or resigned."),
    "ERR_OPERATOR_NOT_CERTIFIED": (422, "The board operator does not hold a live board operation certification."),
    "ERR_VOLUNTEER_NOT_ELIGIBLE": (422, "The volunteer is suspended or resigned."),
    "ERR_SHIFT_OUTSIDE_DRIVE_WINDOW": (422, "The shift falls outside the drive's window."),
    "ERR_QUORUM_NOT_MET": (422, "The review round has not reached quorum."),
    "ERR_COMMITTEE_UNDERSTAFFED": (422, "Fewer than three eligible seated committee members exist."),
    "ERR_GRID_EMPTY": (422, "The grid holds no assigned minutes."),
    "ERR_DIVERSITY_QUOTA_UNMET": (422, "The grid's public affairs share falls below the required minimum."),
    "ERR_WEEK_MINUTES_EXCEEDED": (422, "The placement would push the grid past the broadcast week minute cap."),
    "ERR_PLAYLIST_EMPTY": (422, "A music program's log requires at least one playlist entry."),
    "ERR_EDITED_COPY_STILL_NONCOMPLIANT": (422, "The edited copy still screens at or above the editable threshold."),
    "ERR_POLITICAL_COPY_UNCENSORABLE": (422, "Political candidate copy may not be edited by the station."),
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        status, default_message = ERRORS.get(error_id, (400, "Request refused."))
        self.error_id = error_id
        self.http_status = status
        self.message = message or default_message
        super().__init__(self.message)


def fail(error_id, message=None):
    raise ApiError(error_id, message)
