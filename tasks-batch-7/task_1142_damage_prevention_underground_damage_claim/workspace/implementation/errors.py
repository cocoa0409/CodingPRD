"""Error classes and error ID constants from the scaffold error catalog."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_missing_context(msg="X-User-ID or X-User-Role header missing/malformed or role undeclared"):
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", msg, 400)


def err_invalid_request(msg="Missing required field, invalid enum member, non-positive quantity/amount, malformed datetime"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def err_forbidden(msg="Caller role not in the endpoint's role list"):
    return ApiError("ERR_FORBIDDEN_FOR_ROLE", msg, 403)


def err_ownership(msg="Entity-backed caller acts on a resource owned by another party"):
    return ApiError("ERR_OWNERSHIP_MISMATCH", msg, 403)


def err_segregation(msg="Finalize caller is the same user recorded as the case's investigator"):
    return ApiError("ERR_SEGREGATION_OF_DUTIES", msg, 403)


def err_not_found(msg="Resource id does not resolve"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_invalid_state(msg="Resource state does not permit the requested transition"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def err_contest_window(msg="Contest attempted after contest_deadline_at while allocation still PROPOSED"):
    return ApiError("ERR_CONTEST_WINDOW_CLOSED", msg, 409)


def err_ticket_expired(msg="Locate response submitted against an EXPIRED ticket"):
    return ApiError("ERR_TICKET_EXPIRED", msg, 409)


def err_outside_window(msg="case.occurred_at outside the COMPLETED ticket's [work_start_at, work_end_at)"):
    return ApiError("ERR_DAMAGE_OUTSIDE_TICKET_WINDOW", msg, 409)


def err_period_overlap(msg="QUARTERLY_SUMMARY closed period overlaps a non-SUPERSEDED quarterly report's period"):
    return ApiError("ERR_REPORT_PERIOD_OVERLAP", msg, 409)


def err_locator_inactive(msg="Locate response submitted by a SUSPENDED locator"):
    return ApiError("ERR_LOCATOR_INACTIVE", msg, 409)


def err_amend_chain(msg="amend attempted on a report not in FILED status"):
    return ApiError("ERR_AMEND_CHAIN_BROKEN", msg, 409)


def err_dispute_open(msg="Target already has a dispute in {OPEN, UNDER_REVIEW, COUNTERED}"):
    return ApiError("ERR_DISPUTE_ALREADY_OPEN", msg, 409)


def err_program_suspended(msg="SUSPENDED excavator cannot file new locate tickets"):
    return ApiError("ERR_PROGRAM_SUSPENDED", msg, 409)


def err_no_evidence(msg="Finalize requires evidence_count >= 1 on the case"):
    return ApiError("ERR_NO_SCENE_EVIDENCE", msg, 409)


def err_authority_cap(msg="Finalize with case.subtotal_cents > 5000000 and no override_authority_cap"):
    return ApiError("ERR_INVOICE_AUTHORITY_CAP_EXCEEDED", msg, 409)


def err_write_off_cap(msg="Write-off attempted with amount_due_cents > 20000"):
    return ApiError("ERR_WRITE_OFF_CAP_EXCEEDED", msg, 409)


def err_payment_exceeds(msg="Explicit-invoice payment exceeds that invoice's amount_due_cents"):
    return ApiError("ERR_PAYMENT_EXCEEDS_BALANCE", msg, 409)


def err_timeline_empty(msg="Reconstruct-timeline with no linked ticket, no responses, and no evidence"):
    return ApiError("ERR_TIMELINE_EMPTY", msg, 409)


def err_case_not_closable(msg="Close gate unmet: not FAULT_FINAL + RECOVERED, or a DRAFT incident report exists"):
    return ApiError("ERR_CASE_NOT_CLOSABLE", msg, 409)


def err_invoice_open_dispute(msg="Write-off blocked by a dispute in {OPEN, UNDER_REVIEW, COUNTERED} on the invoice"):
    return ApiError("ERR_INVOICE_HAS_OPEN_DISPUTE", msg, 409)


def err_duplicate_course(msg="TrainingCourse course_code already exists"):
    return ApiError("ERR_DUPLICATE_COURSE_CODE", msg, 409)


def err_window_conflict(msg="Half-open dig window overlaps another OPEN ticket of the same (excavator_id, dig_site_address)"):
    return ApiError("ERR_TICKET_WINDOW_CONFLICT", msg, 409)


def err_stale_version(msg="expected_damage_case_version does not match the case's current version on allocation create"):
    return ApiError("ERR_STALE_VERSION", msg, 412)


def err_evidence_inadmissible(msg="Evidence captured_at is after case.occurred_at + 72 hours"):
    return ApiError("ERR_EVIDENCE_INADMISSIBLE", msg, 422)


def err_window_invalid(msg="work_end_at <= work_start_at, or renew's new_work_end_at <= current work_end_at"):
    return ApiError("ERR_TICKET_WINDOW_INVALID", msg, 422)


def err_dispute_target(msg="dispute target_id does not resolve to an entity of target_type"):
    return ApiError("ERR_DISPUTE_TARGET_MISMATCH", msg, 422)


def err_shares_sum(msg="Supplied fault shares do not sum to exactly 10000 basis points"):
    return ApiError("ERR_SHARES_MUST_SUM_10000", msg, 422)
