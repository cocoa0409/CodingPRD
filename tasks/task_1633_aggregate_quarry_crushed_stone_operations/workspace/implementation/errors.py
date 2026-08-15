"""Error classes with scaffold-defined error IDs and HTTP statuses."""


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_unauthenticated(msg="Authentication required"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def err_forbidden(msg="Role not authorized for this endpoint"):
    return ApiError("ERR_FORBIDDEN", msg, 403)


def err_invalid_request(msg="Invalid request"):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


def err_not_found(msg="Resource not found"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


def err_invalid_state(msg="Invalid state for this operation"):
    return ApiError("ERR_INVALID_STATE", msg, 409)


def err_site_posture_blocked(msg="Site posture blocks this operation"):
    return ApiError("ERR_SITE_POSTURE_BLOCKED", msg, 409)


def err_training_expired(msg="Firing user lacks a current TASK_TRAINING record"):
    return ApiError("ERR_TRAINING_EXPIRED", msg, 409)


def err_permit_acreage_exceeded(msg="Bench release would exceed permitted acres"):
    return ApiError("ERR_PERMIT_ACREAGE_EXCEEDED", msg, 409)


def err_outside_blast_window(msg="Firing outside the daily blasting window"):
    return ApiError("ERR_OUTSIDE_BLAST_WINDOW", msg, 422)


def err_scale_not_certified(msg="Scale not certified or certification expired"):
    return ApiError("ERR_SCALE_NOT_CERTIFIED", msg, 409)


def err_bench_not_released(msg="Bench is not RELEASED"):
    return ApiError("ERR_BENCH_NOT_RELEASED", msg, 409)


def err_bench_sequence_violation(msg="Higher benches must be mined out first"):
    return ApiError("ERR_BENCH_SEQUENCE_VIOLATION", msg, 409)


def err_active_shot_plan(msg="Bench has live shot plans"):
    return ApiError("ERR_ACTIVE_SHOT_PLAN", msg, 409)


def err_holes_incomplete(msg="Drilled hole count below design hole count"):
    return ApiError("ERR_HOLES_INCOMPLETE", msg, 422)


def err_muckpile_depleted(msg="Muckpile is depleted or has insufficient remaining tons"):
    return ApiError("ERR_MUCKPILE_DEPLETED", msg, 409)


def err_stockpile_exists(msg="A stockpile already exists for this site and spec"):
    return ApiError("ERR_STOCKPILE_EXISTS", msg, 409)


def err_stockpile_quarantined(msg="Stockpile is not OPEN"):
    return ApiError("ERR_STOCKPILE_QUARANTINED", msg, 409)


def err_stockpile_not_empty(msg="Stockpile is not empty"):
    return ApiError("ERR_STOCKPILE_NOT_EMPTY", msg, 409)


def err_stockpile_capacity_exceeded(msg="Capacity exceeded"):
    return ApiError("ERR_STOCKPILE_CAPACITY_EXCEEDED", msg, 409)


def err_adjustment_below_reserved(msg="Adjustment would drop on-hand below reserved"):
    return ApiError("ERR_ADJUSTMENT_BELOW_RESERVED", msg, 409)


def err_spec_retired(msg="Product spec is retired"):
    return ApiError("ERR_SPEC_RETIRED", msg, 409)


def err_zone_inactive(msg="Freight zone is inactive"):
    return ApiError("ERR_ZONE_INACTIVE", msg, 409)


def err_over_shipment(msg="Over-shipment beyond 110% tolerance"):
    return ApiError("ERR_OVER_SHIPMENT", msg, 409)


def err_truck_overweight(msg="Net weight exceeds max payload"):
    return ApiError("ERR_TRUCK_OVERWEIGHT", msg, 422)


def err_tare_variance(msg="Tare variance exceeds 2% tolerance"):
    return ApiError("ERR_TARE_VARIANCE", msg, 422)


def err_statement_locked(msg="A live royalty statement covers this ticket's date"):
    return ApiError("ERR_STATEMENT_LOCKED", msg, 409)


def err_statement_period_overlap(msg="Statement period overlaps an existing statement"):
    return ApiError("ERR_STATEMENT_PERIOD_OVERLAP", msg, 409)


def err_statement_not_chronological(msg="Statement period breaks chronological order"):
    return ApiError("ERR_STATEMENT_NOT_CHRONOLOGICAL", msg, 409)


def err_royalty_agreement_required(msg="No ACTIVE royalty agreement covers the date"):
    return ApiError("ERR_ROYALTY_AGREEMENT_REQUIRED", msg, 409)


def err_agreement_already_active(msg="Site already has an ACTIVE royalty agreement"):
    return ApiError("ERR_AGREEMENT_ALREADY_ACTIVE", msg, 409)


def err_bond_below_required(msg="Release would drop coverage below required"):
    return ApiError("ERR_BOND_BELOW_REQUIRED", msg, 409)


def err_open_citations(msg="Inspection has non-terminal citations"):
    return ApiError("ERR_OPEN_CITATIONS", msg, 409)


def err_output_imbalance(msg="Run outputs diverge from input beyond 3%"):
    return ApiError("ERR_OUTPUT_IMBALANCE", msg, 422)


def err_circuit_overlap(msg="Circuit busy or in cooldown"):
    return ApiError("ERR_CIRCUIT_OVERLAP", msg, 409)


def err_truck_already_queued(msg="Truck already has an active queue entry at this site"):
    return ApiError("ERR_TRUCK_ALREADY_QUEUED", msg, 409)


def err_queue_empty(msg="No queued entries for the site"):
    return ApiError("ERR_QUEUE_EMPTY", msg, 409)


def err_sod_violation(msg="Segregation of duties violation"):
    return ApiError("ERR_SOD_VIOLATION", msg, 403)


def err_stale_version(msg="Stale version"):
    return ApiError("ERR_STALE_VERSION", msg, 412)


def err_reversal_blocked(msg="Run void reversal not absorbable"):
    return ApiError("ERR_REVERSAL_BLOCKED", msg, 409)
