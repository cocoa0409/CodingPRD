"""API error type. error_id and http_status come from the scaffold catalog."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# Error IDs (scaffold §1.6)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"                # 401
ERR_FORBIDDEN = "ERR_FORBIDDEN"                            # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                            # 404
ERR_NOT_OWNER = "ERR_NOT_OWNER"                            # 403
ERR_INVALID_STATE = "ERR_INVALID_STATE"                    # 409
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"    # 403
ERR_TRAINING_INCOMPLETE = "ERR_TRAINING_INCOMPLETE"        # 422
ERR_ANIMAL_CAP_EXCEEDED = "ERR_ANIMAL_CAP_EXCEEDED"        # 422
ERR_PROTOCOL_NOT_APPROVED = "ERR_PROTOCOL_NOT_APPROVED"    # 409
ERR_CAGE_MISMATCH = "ERR_CAGE_MISMATCH"                    # 422
ERR_CAGE_OVER_CAPACITY = "ERR_CAGE_OVER_CAPACITY"          # 422
ERR_ROOM_CONFLICT = "ERR_ROOM_CONFLICT"                    # 409
ERR_LITTER_TOO_YOUNG = "ERR_LITTER_TOO_YOUNG"              # 422
ERR_RESOLUTION_OVERDUE = "ERR_RESOLUTION_OVERDUE"          # 422
ERR_INSPECTION_LAPSED = "ERR_INSPECTION_LAPSED"            # 422
ERR_CENSUS_DISCREPANCY = "ERR_CENSUS_DISCREPANCY"          # 422
ERR_GRANT_INSOLVENT = "ERR_GRANT_INSOLVENT"                # 402
ERR_GRANT_EXHAUSTED = "ERR_GRANT_EXHAUSTED"                # 402
ERR_DUPLICATE = "ERR_DUPLICATE"                            # 409
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                # 400
ERR_STALE_VERSION = "ERR_STALE_VERSION"                    # 412
ERR_SERIOUS_DEVIATION_NOT_CLOSABLE = "ERR_SERIOUS_DEVIATION_NOT_CLOSABLE"  # 422
ERR_INVALID_VOTE_TALLY = "ERR_INVALID_VOTE_TALLY"          # 422
ERR_BOOKING_IN_PAST = "ERR_BOOKING_IN_PAST"                # 422


def invalid_request(msg):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def not_found(msg):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_state(msg):
    return ApiError(ERR_INVALID_STATE, 409, msg)
