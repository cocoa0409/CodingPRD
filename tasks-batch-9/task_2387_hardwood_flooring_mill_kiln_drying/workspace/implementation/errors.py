"""Error catalogue for the Hardwood Flooring Mill & Kiln Drying API.

Every error_id / HTTP status pair here comes straight from PRD section 5 and the
SCAFFOLD `errors` table -- nothing is invented or defaulted.
"""

ERROR_CATALOG = {
    "ERR_UNAUTHENTICATED": (401, "Authentication required."),
    "ERR_FORBIDDEN_ROLE": (403, "Role not permitted for this operation."),
    "ERR_INVALID_REQUEST": (400, "Request payload failed schema validation."),
    "ERR_CONFIG_NOT_FOUND": (404, "Referenced configuration record was not found."),
    "ERR_RECEIPT_NOT_FOUND": (404, "Green receipt was not found."),
    "ERR_CHARGE_NOT_FOUND": (404, "Kiln charge was not found."),
    "ERR_LOT_NOT_FOUND": (404, "Flooring lot was not found."),
    "ERR_GRADE_RUN_NOT_FOUND": (404, "Grade run was not found."),
    "ERR_PREFINISH_RUN_NOT_FOUND": (404, "Prefinish run was not found."),
    "ERR_BATCH_NOT_FOUND": (404, "Byproduct batch was not found."),
    "ERR_CLAIM_NOT_FOUND": (404, "Warranty claim was not found."),
    "ERR_STALE_SPECIES_PROFILE_VERSION": (412, "Species profile version is stale."),
    "ERR_STALE_LOT_VERSION": (412, "Flooring lot version is stale."),
    "ERR_SEGREGATION_OF_DUTIES": (403, "The submitter of a claim may not adjudicate it."),
    "ERR_RECEIPT_STATE_INVALID": (409, "Green receipt is not in a state allowing this operation."),
    "ERR_CHARGE_STATE_INVALID": (409, "Kiln charge is not in a state allowing this operation."),
    "ERR_CHAMBER_STATE_INVALID": (409, "Kiln chamber is not in a state allowing this operation."),
    "ERR_LOT_STATE_INVALID": (409, "Flooring lot is not in a state allowing this operation."),
    "ERR_GRADE_RUN_STATE_INVALID": (409, "Grade run is not in a state allowing this operation."),
    "ERR_PREFINISH_RUN_STATE_INVALID": (409, "Prefinish run is not in a state allowing this operation."),
    "ERR_CLAIM_STATE_INVALID": (409, "Warranty claim is not in a state allowing this operation."),
    "ERR_PRODUCT_LINE_POSTURE_BLOCKED": (409, "Product line posture blocks prefinishing."),
    "ERR_REDRY_LIMIT_EXCEEDED": (409, "Charge has exhausted its redry allowance."),
    "ERR_LOT_NOT_GRADED": (409, "Only a graded lot may be prefinished."),
    "ERR_MC_PLAN_DEVIATION": (422, "Charge green moisture deviates from the schedule design."),
    "ERR_PROFILE_TOLERANCE_EXCEEDED": (422, "Milled width is outside the profile tolerance."),
    "ERR_BYPRODUCT_SALE_EXISTS": (409, "Lot has byproduct sales and cannot be voided."),
    "ERR_SPECIES_MISMATCH": (422, "Receipt species does not match the charge schedule species."),
    "ERR_CORE_STOCK_REQUIRED": (422, "Engineered lots require core stock."),
    "ERR_CORE_STOCK_NOT_ALLOWED": (422, "Solid lots may not reference core stock."),
    "ERR_CORE_STOCK_LINE_MISMATCH": (422, "Core stock belongs to a different product line."),
    "ERR_GRADE_RUN_LOT_MISMATCH": (422, "Grade run belongs to a different flooring lot."),
    "ERR_CHARACTER_GRADE_NOT_PERMITTED": (422, "Character grades require the MILL_CHARACTER ruleset."),
    "ERR_PREFINISH_WINDOW_INVALID": (422, "Prefinish window is empty or too long."),
    "ERR_CHAMBER_WINDOW_CONFLICT": (409, "Chamber occupancy windows collide."),
    "ERR_INSTALL_DATE_IN_FUTURE": (422, "Installation date is in the future."),
    "ERR_WARRANTY_PERIOD_EXPIRED": (422, "Warranty period has expired."),
    "ERR_ACCEPTED_BF_EXCEEDS_RECEIVED": (422, "Accepted board feet exceed the received quantity."),
    "ERR_CHAMBER_CAPACITY_EXCEEDED": (422, "Charge exceeds the chamber capacity."),
    "ERR_CHARGE_DRY_BF_EXCEEDED": (422, "Lot draw exceeds the remaining kiln-dry volume."),
    "ERR_CORE_STOCK_INSUFFICIENT": (422, "Core stock has insufficient available square footage."),
    "ERR_MILL_MASS_BALANCE_VIOLATION": (422, "Milling outputs exceed the kiln-dry input."),
    "ERR_WASTE_LIMIT_EXCEEDED": (422, "Unaccounted waste exceeds the mill limit."),
    "ERR_NO_GRADE_BUNDLES": (422, "Grade run has no bundles."),
    "ERR_BUNDLE_BF_EXCEEDS_LOT": (422, "Bundle board feet exceed the lot net flooring volume."),
    "ERR_PREFINISH_CAPACITY_EXCEEDED": (422, "Prefinish line capacity exceeded for the overlapping window set."),
    "ERR_BYPRODUCT_QUANTITY_EXCEEDS_BATCH": (422, "Sale quantity exceeds the unsold batch tonnage."),
    "ERR_TOO_MANY_OPEN_CLAIMS": (409, "Product line already carries the maximum open claims."),
    "ERR_DUPLICATE_CODE": (409, "Configuration code already exists."),
    "ERR_ADJUDICATED_SF_EXCEEDS_CLAIM": (422, "Adjudicated area exceeds the claimed area."),
    "ERR_WARRANTY_RESERVE_INSUFFICIENT": (422, "Warranty reserve cannot cover the adjudicated liability."),
    "ERR_NOT_FOUND": (404, "Resource was not found."),
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, status=None):
        status_default, message_default = ERROR_CATALOG.get(error_id, (400, "Request failed."))
        self.error_id = error_id
        self.message = message or message_default
        self.status = status or status_default
        super().__init__(self.message)


def invalid(message=None):
    return ApiError("ERR_INVALID_REQUEST", message)
