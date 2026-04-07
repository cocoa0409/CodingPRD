export type ApiErrorCode =
  | "ERR_NOT_FOUND"
  | "ERR_INVALID_REQUEST"
  | "ERR_INVALID_STATE_TRANSITION"
  | "ERR_MISSING_OR_INVALID_CONTEXT_HEADER"
  | "ERR_SESSION_NOT_ACTIVE"
  | "ERR_FORBIDDEN_FOR_ACTOR"
  | "ERR_PROGRAM_FROZEN"
  | "ERR_PROGRAM_CLOSED"
  | "ERR_PROGRAM_REVIEW_REQUIRED"
  | "ERR_PROGRAM_NOT_ELIGIBLE_TO_UNFREEZE"
  | "ERR_PROGRAM_NOT_ELIGIBLE_TO_CLOSE"
  | "ERR_CUSTOMER_LOCKED"
  | "ERR_CUSTOMER_CLOSED"
  | "ERR_CUSTOMER_NOT_ELIGIBLE"
  | "ERR_OUT_OF_STOCK"
  | "ERR_BUILD_LOT_QUARANTINED"
  | "ERR_ORDER_ON_HOLD"
  | "ERR_ORDER_PAYMENT_REQUIRED"
  | "ERR_ORDER_NOT_CANCELABLE"
  | "ERR_PAYMENT_NOT_REFUNDABLE"
  | "ERR_PAYMENT_NOT_DISPUTABLE"
  | "ERR_DEVICE_NOT_ACTIVATABLE"
  | "ERR_DEVICE_QUARANTINED"
  | "ERR_CARE_PLAN_NOT_ELIGIBLE"
  | "ERR_TRADEIN_NOT_ELIGIBLE"
  | "ERR_TRADEIN_REQUIRES_APPRAISAL"
  | "ERR_RETURN_NOT_ELIGIBLE"
  | "ERR_RETURN_NOT_RESOLVABLE"
  | "ERR_ALERT_NOT_RESOLVABLE"
  | "ERR_CLAIM_NOT_ELIGIBLE"
  | "ERR_CLAIM_NOT_RESOLVABLE"
  | "ERR_ADJUSTMENT_NOT_ELIGIBLE"
  | "ERR_ADJUSTMENT_NOT_VOIDABLE"
  | "ERR_IDEMPOTENCY_CONFLICT";

export class ApiError extends Error {
  public readonly status: number;
  public readonly code: ApiErrorCode;

  constructor(status: number, code: ApiErrorCode, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export function notFound(message = "Not found"): ApiError {
  return new ApiError(404, "ERR_NOT_FOUND", message);
}

export function badRequest(code: ApiErrorCode, message: string): ApiError {
  return new ApiError(400, code, message);
}

export function forbidden(message: string): ApiError {
  return new ApiError(403, "ERR_FORBIDDEN_FOR_ACTOR", message);
}

export function assertUnreachable(x: never): never {
  throw new Error(`Unreachable: ${String(x)}`);
}
