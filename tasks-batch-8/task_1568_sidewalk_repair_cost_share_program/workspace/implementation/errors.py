"""API error type carrying the scaffold's exact error_id / HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def bad_request(msg):
    return ApiError('ERR_INVALID_REQUEST', 400, msg)


def unauthenticated(msg='Authentication headers missing or role not recognized'):
    return ApiError('ERR_UNAUTHENTICATED', 401, msg)


def forbidden_role(msg='Role not authorized for this endpoint'):
    return ApiError('ERR_FORBIDDEN_ROLE', 403, msg)


def ownership(msg='Actor does not own the target resource'):
    return ApiError('ERR_OWNERSHIP_MISMATCH', 403, msg)


def segregation(msg='Segregation of duties violation'):
    return ApiError('ERR_SEGREGATION_OF_DUTIES', 403, msg)


NOT_FOUND = {
    'cycle': ('ERR_PROGRAM_CYCLE_NOT_FOUND', 'Program cycle not found'),
    'owner': ('ERR_PROPERTY_OWNER_NOT_FOUND', 'Property owner not found'),
    'parcel': ('ERR_PARCEL_NOT_FOUND', 'Parcel not found'),
    'segment': ('ERR_SEGMENT_NOT_FOUND', 'Segment not found'),
    'defect': ('ERR_DEFECT_NOT_FOUND', 'Defect not found'),
    'notice': ('ERR_REPAIR_NOTICE_NOT_FOUND', 'Repair notice not found'),
    'application': ('ERR_APPLICATION_NOT_FOUND', 'Cost-share application not found'),
    'batch': ('ERR_BID_BATCH_NOT_FOUND', 'Bid batch not found'),
    'work_item': ('ERR_WORK_ITEM_NOT_FOUND', 'Batch work item not found'),
    'contractor': ('ERR_CONTRACTOR_NOT_FOUND', 'Contractor not found'),
    'bid': ('ERR_BID_NOT_FOUND', 'Bid not found'),
    'forestry': ('ERR_FORESTRY_REVIEW_NOT_FOUND', 'Forestry review not found'),
    'lien': ('ERR_LIEN_CASE_NOT_FOUND', 'Lien case not found'),
}


def not_found(kind):
    eid, msg = NOT_FOUND[kind]
    return ApiError(eid, 404, msg)
