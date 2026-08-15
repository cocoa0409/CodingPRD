"""Error classes and error ID factories (scaffold section 1.6 error catalog)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_unauthenticated(msg="Missing or invalid X-User-Role / X-User-ID headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_unauthorized_role(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_UNAUTHORIZED_ROLE", 403, msg)


def err_ownership(msg="Entity-backed actor does not own the target resource"):
    return ApiError("ERR_OWNERSHIP_VIOLATION", 403, msg)


def err_not_found(msg="Referenced resource id does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def err_invalid_request(msg="Missing/malformed field, invalid enum, or invalid datetime ordering"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_stale_version(msg="expected_<parent>_version does not match the parent's current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def err_invalid_state(msg="Entity state machine does not permit the requested transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_event_phase_forbidden(msg="Operation not allowed in the event's current phase"):
    return ApiError("ERR_EVENT_PHASE_FORBIDDEN", 409, msg)


def err_catalog_frozen(msg="Catalog structure edits blocked once the event has left CATALOGING"):
    return ApiError("ERR_CATALOG_FROZEN", 409, msg)


def err_solicitation_cooldown(msg="Donor has a solicitation inside the cooldown window"):
    return ApiError("ERR_SOLICITATION_COOLDOWN", 409, msg)


def err_solicitation_not_pledged(msg="Item receipt requires solicitation status PLEDGED"):
    return ApiError("ERR_SOLICITATION_NOT_PLEDGED", 409, msg)


def err_item_not_valued(msg="Attach requires item status VALUED (approved valuation)"):
    return ApiError("ERR_ITEM_NOT_VALUED", 409, msg)


def err_item_already_bundled(msg="Item already attached to a bundle"):
    return ApiError("ERR_ITEM_ALREADY_BUNDLED", 409, msg)


def err_sod(msg="Valuation approver/rejecter is the same user who submitted it"):
    return ApiError("ERR_SOD_VIOLATION", 403, msg)


def err_valuation_already_decided(msg="Valuation not in SUBMITTED (already decided or superseded)"):
    return ApiError("ERR_VALUATION_ALREADY_DECIDED", 409, msg)


def err_bundle_empty(msg="Publish requires at least one member item"):
    return ApiError("ERR_BUNDLE_EMPTY", 422, msg)


def err_min_bid_below_floor(msg="Min-bid override below event min_bid_floor_cents"):
    return ApiError("ERR_MIN_BID_BELOW_FLOOR", 422, msg)


def err_bid_below_minimum(msg="Bid amount below min_next_bid_cents"):
    return ApiError("ERR_BID_BELOW_MINIMUM", 422, msg)


def err_bidder_event_mismatch(msg="Bidder is registered to a different gala event than the bundle's"):
    return ApiError("ERR_BIDDER_EVENT_MISMATCH", 403, msg)


def err_bidder_suspended(msg="Bidder status is SUSPENDED"):
    return ApiError("ERR_BIDDER_SUSPENDED", 403, msg)


def err_payment_method_required(msg="Bidder has no payment method on file"):
    return ApiError("ERR_PAYMENT_METHOD_REQUIRED", 422, msg)


def err_invoice_not_payable(msg="Invoice payment_status not in {UNPAID, PARTIALLY_PAID}"):
    return ApiError("ERR_INVOICE_NOT_PAYABLE", 409, msg)


def err_payment_exceeds_balance(msg="Payment amount outside 1..outstanding_cents"):
    return ApiError("ERR_PAYMENT_EXCEEDS_BALANCE", 422, msg)


def err_refund_forbidden(msg="Refund requires PAID and no REDEEMED certificate"):
    return ApiError("ERR_REFUND_FORBIDDEN", 409, msg)


def err_writeoff_forbidden(msg="Write-off requires payment_status UNPAID"):
    return ApiError("ERR_WRITEOFF_FORBIDDEN", 409, msg)


def err_certificate_not_redeemable(msg="Certificate not in ISSUED (incl. post-sweep EXPIRED)"):
    return ApiError("ERR_CERTIFICATE_NOT_REDEEMABLE", 409, msg)


def err_redemption_window_invalid(msg="Scheduled window outside closed containment [valid_from, grace_end_at] or start >= end"):
    return ApiError("ERR_REDEMPTION_WINDOW_INVALID", 422, msg)


def err_blackout_conflict(msg="Scheduled window intersects a member experience item's blackout"):
    return ApiError("ERR_BLACKOUT_CONFLICT", 409, msg)


def err_disposition_forbidden(msg="Disposition not in the required step for decide/donor-response"):
    return ApiError("ERR_DISPOSITION_FORBIDDEN", 409, msg)


def err_rollover_target_invalid(msg="Rollover target missing, same as source, or not in {DRAFT, SOLICITING, CATALOGING}"):
    return ApiError("ERR_ROLLOVER_TARGET_INVALID", 409, msg)


def err_ack_threshold_not_met(msg="Acknowledgment fmv_cents below event ack_threshold_cents"):
    return ApiError("ERR_ACK_THRESHOLD_NOT_MET", 422, msg)


def err_reconcile_blocked(msg="Reconcile requires all invoices terminal, paid invoices fulfilled/expired, all dispositions executed"):
    return ApiError("ERR_RECONCILE_BLOCKED", 409, msg)


def err_no_published_bundles(msg="Opening bidding requires at least one PUBLISHED bundle"):
    return ApiError("ERR_NO_PUBLISHED_BUNDLES", 409, msg)


def err_paddle_taken(msg="paddle_no already used within the gala event"):
    return ApiError("ERR_PADDLE_TAKEN", 409, msg)
