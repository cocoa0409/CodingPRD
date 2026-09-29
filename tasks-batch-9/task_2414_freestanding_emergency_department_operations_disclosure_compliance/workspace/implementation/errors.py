"""Error catalogue (SCAFFOLD.yaml `errors`, PRD section 5)."""


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        spec = ERROR_CATALOG.get(error_id, (400, "Request could not be processed"))
        self.error_id = error_id
        self.http_status = http_status if http_status is not None else spec[0]
        self.message = message if message is not None else spec[1]


ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": (401, "Authentication headers missing or role unrecognized"),
    "ERR_UNAUTHORIZED": (403, "Role not permitted for this operation"),
    "ERR_SEGREGATION_OF_DUTIES": (403, "The same operator may not perform both halves of this control"),
    "ERR_INVALID_REQUEST": (400, "Request body or query parameters are malformed"),
    "ERR_FACILITY_NOT_FOUND": (404, "Facility not found"),
    "ERR_DISCLOSURE_TEMPLATE_NOT_FOUND": (404, "Disclosure template not found"),
    "ERR_PAYER_CONTRACT_NOT_FOUND": (404, "Payer contract not found"),
    "ERR_PHYSICIAN_SHIFT_NOT_FOUND": (404, "Physician shift not found"),
    "ERR_VOLUME_FORECAST_NOT_FOUND": (404, "Volume forecast not found"),
    "ERR_TRANSFER_AGREEMENT_NOT_FOUND": (404, "Transfer agreement not found"),
    "ERR_AMBULANCE_MOU_NOT_FOUND": (404, "Ambulance MOU not found"),
    "ERR_ENCOUNTER_NOT_FOUND": (404, "Encounter not found"),
    "ERR_ANCILLARY_ORDER_NOT_FOUND": (404, "Ancillary order not found"),
    "ERR_TRANSFER_ORDER_NOT_FOUND": (404, "Transfer order not found"),
    "ERR_CLAIM_NOT_FOUND": (404, "Claim not found"),
    "ERR_DISPUTE_CASE_NOT_FOUND": (404, "Dispute case not found"),
    "ERR_STALE_FACILITY_VERSION": (412, "Facility version is stale; re-read the facility and retry"),
    "ERR_STALE_ENCOUNTER_VERSION": (412, "Encounter version is stale; re-read the encounter and retry"),
    "ERR_TEMPLATE_NOT_PUBLISHABLE": (409, "Only a DRAFT disclosure template can be published"),
    "ERR_DISCLOSURE_DECISION_ALREADY_RECORDED": (
        409,
        "A disclosure decision has already been recorded for this encounter",
    ),
    "ERR_INVALID_ENCOUNTER_STATE": (409, "Encounter clinical state does not permit this operation"),
    "ERR_INVALID_ANCILLARY_ORDER_STATE": (409, "Ancillary order is not in ORDERED status"),
    "ERR_INVALID_TRANSFER_ORDER_STATE": (409, "Transfer order status does not permit this transition"),
    "ERR_INVALID_CLAIM_STATE": (409, "Claim status does not permit this operation"),
    "ERR_INVALID_DISPUTE_STATE": (409, "Dispute case status does not permit this operation"),
    "ERR_MSE_NOT_COMPLETE": (
        409,
        "The medical screening examination must be complete before observation or transfer",
    ),
    "ERR_TRANSFER_CERTIFICATION_REQUIRED": (
        422,
        "Physician certification that transfer benefits outweigh risks is required",
    ),
    "ERR_STABILIZATION_REQUIRED": (
        422,
        "An unstable patient may not be discharged and may only be transferred under an "
        "unstable-accepting agreement with critical-care transport",
    ),
    "ERR_WAIVER_NOT_EMERGENT": (422, "An emergent disclosure waiver requires acuity level 4 or 5"),
    "ERR_FACILITY_POSTURE_BLOCKED": (409, "Facility compliance posture blocks this operation"),
    "ERR_NO_PUBLISHED_DISCLOSURE": (
        409,
        "The facility has no published disclosure template to present at registration",
    ),
    "ERR_SIGNAGE_ELEMENTS_INCOMPLETE": (
        422,
        "Attested signage elements do not cover every required element",
    ),
    "ERR_OUT_OF_SCOPE_SERVICE": (422, "Ordered service is outside the facility's licensed on-site scope"),
    "ERR_AGREEMENT_WINDOW_CONFLICT": (
        409,
        "Transfer agreement window collides with an existing agreement for the same hospital and service line",
    ),
    "ERR_CLINICIAN_DOUBLE_BOOKED": (409, "Clinician already has an overlapping coverage block"),
    "ERR_AGREEMENT_NOT_ACTIVE": (422, "Transfer agreement is not active on the current date"),
    "ERR_MOU_WINDOW_NOT_COVERING": (
        422,
        "Ambulance MOU coverage window does not cover the requested transport time",
    ),
    "ERR_PAYER_CONTRACT_NOT_ACTIVE": (422, "Payer contract is not active on the current date"),
    "ERR_TRANSFER_CAPABILITY_INSUFFICIENT": (
        422,
        "Receiving hospital does not cover this service line at the required capability tier",
    ),
    "ERR_MOU_LEVEL_INSUFFICIENT": (422, "Ambulance level of care is insufficient for this acuity"),
    "ERR_IDR_NOT_ELIGIBLE": (422, "Claim is not eligible for independent dispute resolution"),
    "ERR_OBSERVATION_CAPACITY_EXCEEDED": (409, "No licensed observation bed is available"),
    "ERR_AMBULANCE_CAPACITY_EXCEEDED": (409, "No ambulance unit is available under this MOU"),
    "ERR_COVERAGE_CAPACITY_EXCEEDED": (409, "Concurrent physician coverage cap exceeded"),
    "ERR_NEGOTIATION_ROUNDS_EXHAUSTED": (409, "Open-negotiation rounds are exhausted"),
    "ERR_NEGOTIATION_NOT_EXHAUSTED": (422, "Open negotiation must be exhausted before initiating IDR"),
    "ERR_AWARD_OUT_OF_RANGE": (
        422,
        "Award must fall between the last offer and the last counteroffer, inclusive",
    ),
    "ERR_DUPLICATE_TEMPLATE_VERSION": (409, "Template version label already used at this facility"),
    "ERR_CLAIM_ALREADY_EXISTS": (409, "A claim already exists for this encounter"),
    "ERR_NOT_FOUND": (404, "Resource not found"),
    "ERR_METHOD_NOT_ALLOWED": (405, "Method not allowed for this path"),
    "ERR_INTERNAL": (500, "Internal server error"),
}


def bad_request(message=None):
    return ApiError("ERR_INVALID_REQUEST", message)
