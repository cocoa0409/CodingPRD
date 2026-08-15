"""Error type carrying the scaffold-declared error_id / http_status.

All ids and statuses come from the SCAFFOLD.yaml section 1.6 error catalog
and PRD section 5.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def unauthenticated(msg="Missing or unrecognized X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def forbidden(msg="The acting role is not permitted to perform this operation"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def sod_violation(msg="The replant approver/rejector must differ from the proposer"):
    return ApiError("ERR_SOD_VIOLATION", 403, msg)


def not_found(msg="A path identifier or referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def malformed(msg="Request body is missing a required field or is malformed"):
    return ApiError("ERR_MALFORMED_REQUEST", 400, msg)


def stale_version(msg="The expected version does not match the current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def invalid_state(msg="The resource is not in a valid state for the requested transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def posture_forbids(msg="The season posture does not permit this operation"):
    return ApiError("ERR_POSTURE_FORBIDS", 409, msg)


def posture_guard(msg="An advance-posture guard condition is not met"):
    return ApiError("ERR_POSTURE_GUARD_FAILED", 409, msg)


def outside_harvest_window(msg="work_date is outside the season harvest window"):
    return ApiError("ERR_OUTSIDE_HARVEST_WINDOW", 422, msg)


def outside_shipping_window(msg="The instant or window is outside the season shipping window"):
    return ApiError("ERR_OUTSIDE_SHIPPING_WINDOW", 422, msg)


def block_not_harvestable(msg="The block's rotation_state is not HARVESTABLE"):
    return ApiError("ERR_BLOCK_NOT_HARVESTABLE", 409, msg)


def block_occupied(msg="The block is not in the required rotation state for this operation"):
    return ApiError("ERR_BLOCK_OCCUPIED", 409, msg)


def block_not_ucut(msg="The block is not designated for choose-and-cut retail"):
    return ApiError("ERR_BLOCK_NOT_UCUT", 422, msg)


def crew_not_active(msg="The crew is not ACTIVE"):
    return ApiError("ERR_CREW_NOT_ACTIVE", 409, msg)


def buyer_credit_hold(msg="The buyer is not in GOOD_STANDING"):
    return ApiError("ERR_BUYER_CREDIT_HOLD", 422, msg)


def ticket_block_mismatch(msg="A ticket line's allocation does not belong to the ticket's block"):
    return ApiError("ERR_TICKET_BLOCK_MISMATCH", 422, msg)


def allocation_not_cut(msg="The allocation is not in CUT status or lacks cut-but-unloaded headroom"):
    return ApiError("ERR_ALLOCATION_NOT_CUT", 409, msg)


def ticket_not_voidable(msg="The ticket cannot be voided in the current posture or allocation state"):
    return ApiError("ERR_TICKET_NOT_VOIDABLE", 409, msg)


def order_has_cut_allocations(msg="The order has allocations that are already cut or loaded"):
    return ApiError("ERR_ORDER_HAS_CUT_ALLOCATIONS", 409, msg)


def no_eligible_inventory(msg="No eligible inventory is available to allocate"):
    return ApiError("ERR_NO_ELIGIBLE_INVENTORY", 422, msg)


def insufficient_standing(msg="delivered_count exceeds the bucket's available_count"):
    return ApiError("ERR_INSUFFICIENT_STANDING", 422, msg)


def cull_exceeds_standing(msg="cull count exceeds the bucket's available_count"):
    return ApiError("ERR_CULL_EXCEEDS_STANDING", 422, msg)


def bucket_empty(msg="The bucket has no standing trees"):
    return ApiError("ERR_BUCKET_EMPTY", 422, msg)


def crew_double_booked(msg="The crew already has a POSTED ticket on this work_date"):
    return ApiError("ERR_CREW_DOUBLE_BOOKED", 409, msg)


def dock_window_conflict(msg="The pickup window plus buffer overlaps another load of the season"):
    return ApiError("ERR_DOCK_WINDOW_CONFLICT", 409, msg)


def load_over_capacity(msg="The line would push the load above its capacity_units"):
    return ApiError("ERR_LOAD_OVER_CAPACITY", 422, msg)


def cut_exceeds_allocation(msg="cut_count exceeds the allocation's uncut remainder"):
    return ApiError("ERR_CUT_EXCEEDS_ALLOCATION", 422, msg)


def return_exceeds_delivered(msg="returned_count exceeds delivered_count"):
    return ApiError("ERR_RETURN_EXCEEDS_DELIVERED", 422, msg)


def credit_limit_exceeded(msg="The order would push the buyer's exposure above the credit limit"):
    return ApiError("ERR_CREDIT_LIMIT_EXCEEDED", 422, msg)
