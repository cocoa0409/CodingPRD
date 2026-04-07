export type ActorRole = 'SellerAdmin' | 'SellerAR' | 'BuyerAP' | 'Auditor' | 'System';

export type CustomerStatus = 'ACTIVE' | 'CREDIT_HOLD' | 'FROZEN' | 'CLOSED';

export type ContractStatus = 'DRAFT' | 'ACTIVE' | 'SUSPENDED' | 'TERMINATED';

export type POStatus = 'OPEN' | 'ACKNOWLEDGED' | 'CLOSED' | 'CANCELLED';

export type InvoiceStatus = 'DRAFT' | 'FINALIZED' | 'SENT' | 'ACCEPTED' | 'VOIDED' | 'CLOSED';

export type InvoiceType = 'STANDARD' | 'FINANCE_CHARGE';

export type CollectionsStage = 'CURRENT' | 'REMINDER' | 'FINAL_NOTICE' | 'COLLECTIONS';

export type MatchStatus = 'NOT_APPLICABLE' | 'MATCHED' | 'EXCEPTION';

export type PaymentStatus = 'INITIATED' | 'CLEARED' | 'FAILED' | 'REVERSED';

export type DisputeStatus = 'OPEN' | 'IN_REVIEW' | 'PROPOSED' | 'ESCALATED' | 'CLOSED' | 'WITHDRAWN';

export type DisputeReason = 'PRICE_MISMATCH' | 'MISSING_RECEIPT' | 'SERVICE_QUALITY' | 'TAX_ERROR' | 'DUPLICATE_INVOICE' | 'FRAUD';

export type CreditMemoStatus = 'DRAFT' | 'ISSUED' | 'VOIDED';

export type CreditMemoType = 'GOODWILL' | 'DISPUTE_RESOLUTION' | 'EARLY_PAY_DISCOUNT';

export const ErrorCodes = {
  NOT_FOUND: 'ERR_NOT_FOUND',
  INVALID_REQUEST: 'ERR_INVALID_REQUEST',
  INVALID_STATE_TRANSITION: 'ERR_INVALID_STATE_TRANSITION',
  FORBIDDEN_FOR_ROLE: 'ERR_FORBIDDEN_FOR_ROLE',
  MISSING_OR_INVALID_USER_CONTEXT_HEADER: 'ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER',
  CUSTOMER_FROZEN: 'ERR_CUSTOMER_FROZEN',
  CUSTOMER_STILL_FROZEN: 'ERR_CUSTOMER_STILL_FROZEN',
  CUSTOMER_ON_HOLD: 'ERR_CUSTOMER_ON_HOLD',
  CUSTOMER_CLOSED: 'ERR_CUSTOMER_CLOSED',
  CUSTOMER_NOT_SETTLED: 'ERR_CUSTOMER_NOT_SETTLED',
  CONTRACT_INACTIVE: 'ERR_CONTRACT_INACTIVE',
  BILLING_CAP_EXCEEDED: 'ERR_BILLING_CAP_EXCEEDED',
  PO_REQUIRED: 'ERR_PO_REQUIRED',
  PO_NOT_OPEN: 'ERR_PO_NOT_OPEN',
  PO_HAS_INVOICES: 'ERR_PO_HAS_INVOICES',
  DUPLICATE_PO_NUMBER: 'ERR_DUPLICATE_PO_NUMBER',
  RECEIPT_EXCEEDS_TOLERANCE: 'ERR_RECEIPT_EXCEEDS_TOLERANCE',
  DUPLICATE_EXTERNAL_REF: 'ERR_DUPLICATE_EXTERNAL_REF',
  MATCH_EXCEPTION: 'ERR_MATCH_EXCEPTION',
  DISPUTE_ALREADY_ACTIVE: 'ERR_DISPUTE_ALREADY_ACTIVE',
  DISPUTE_WINDOW_CLOSED: 'ERR_DISPUTE_WINDOW_CLOSED',
  COLLECTIONS_RESTRICTS_DISPUTES: 'ERR_COLLECTIONS_RESTRICTS_DISPUTES',
  DISPUTE_AMOUNT_EXCEEDS_AVAILABLE: 'ERR_DISPUTE_AMOUNT_EXCEEDS_AVAILABLE',
  DISPUTE_REASON_NOT_ALLOWED: 'ERR_DISPUTE_REASON_NOT_ALLOWED',
  INVOICE_NOT_DISPUTABLE: 'ERR_INVOICE_NOT_DISPUTABLE',
  PAYMENT_EXCEEDS_ALLOWED: 'ERR_PAYMENT_EXCEEDS_ALLOWED',
  INVOICE_NOT_PAYABLE: 'ERR_INVOICE_NOT_PAYABLE',
  PERIOD_HAS_PENDING_PAYMENTS: 'ERR_PERIOD_HAS_PENDING_PAYMENTS',
  CREDIT_EXCEEDS_AUTHORITY: 'ERR_CREDIT_EXCEEDS_AUTHORITY',
  CREDIT_MEMO_LOCKED: 'ERR_CREDIT_MEMO_LOCKED',
  INVOICE_NOT_CREDITABLE: 'ERR_INVOICE_NOT_CREDITABLE',
  INVOICE_HAS_PAYMENTS: 'ERR_INVOICE_HAS_PAYMENTS',
  INVOICE_HAS_DISPUTE: 'ERR_INVOICE_HAS_DISPUTE',
  BOOKS_CLOSED: 'ERR_BOOKS_CLOSED',
  WRITE_OFF_NOT_ALLOWED: 'ERR_WRITE_OFF_NOT_ALLOWED',
  IDEMPOTENCY_CONFLICT: 'ERR_IDEMPOTENCY_CONFLICT',
  LEDGER_INCONSISTENT: 'ERR_LEDGER_INCONSISTENT',
} as const;

export type ErrorCode = typeof ErrorCodes[keyof typeof ErrorCodes];

export class ApiError extends Error {
  code: ErrorCode;
  statusCode: number;

  constructor(code: ErrorCode, message: string, statusCode: number = 400) {
    super(message);
    this.code = code;
    this.statusCode = statusCode;
  }
}

export interface RequestContext {
  actorId: string;
  actorRole: ActorRole;
  workspaceId?: string;
  idempotencyKey?: string;
}

export interface WorkspaceRow {
  id: string;
  name: string;
  currency: string;
  period_index: number;
  books_closed_through_period_index: number | null;
  created_at: string;
}

export interface CustomerRow {
  id: string;
  workspace_id: string;
  display_name: string;
  external_customer_ref: string | null;
  status: CustomerStatus;
  credit_limit_cents: number;
  balance_due_cents: number;
  unapplied_cash_cents: number;
  available_credit_cents: number;
  freeze_reason: string | null;
  freeze_period_index: number | null;
  last_fraud_dispute_closed_period: number | null;
  last_reversal_period_index: number | null;
  created_at: string;
}

export interface ContractRow {
  id: string;
  workspace_id: string;
  customer_id: string;
  name: string;
  status: ContractStatus;
  payment_terms_periods: number;
  requires_po: number;
  billing_cap_cents_per_period: number | null;
  created_at: string;
}

export interface PurchaseOrderRow {
  id: string;
  workspace_id: string;
  customer_id: string;
  po_number: string;
  status: POStatus;
  created_at: string;
}

export interface PurchaseOrderLineRow {
  id: string;
  purchase_order_id: string;
  description: string;
  ordered_units: number;
  unit_price_cents: number;
  is_service: number;
  received_units: number;
  net_billed_units: number;
}

export interface InvoiceRow {
  id: string;
  workspace_id: string;
  customer_id: string;
  contract_id: string;
  purchase_order_id: string | null;
  external_invoice_ref: string | null;
  document_number: string | null;
  status: InvoiceStatus;
  type: InvoiceType;
  invoice_total_cents: number;
  amount_due_cents: number;
  amount_disputed_cents: number;
  amount_paid_cents: number;
  amount_credited_cents: number;
  amount_written_off_cents: number;
  collections_stage: CollectionsStage;
  match_status: MatchStatus;
  issued_period_index: number | null;
  delivered_period_index: number | null;
  accepted_period_index: number | null;
  due_period_index: number | null;
  is_final_invoice: number;
  parent_invoice_id: string | null;
  created_at: string;
}

export interface InvoiceLineRow {
  id: string;
  invoice_id: string;
  purchase_order_line_id: string | null;
  description: string;
  quantity_units: number;
  unit_price_cents: number;
  line_total_cents: number;
  credited_amount_cents: number;
}

export interface PaymentRow {
  id: string;
  workspace_id: string;
  customer_id: string;
  amount_cents: number;
  status: PaymentStatus;
  initiated_period_index: number | null;
  cleared_period_index: number | null;
  reversed_period_index: number | null;
  created_at: string;
}

export interface PaymentAllocationRow {
  id: string;
  payment_id: string;
  invoice_id: string;
  amount_cents: number;
  is_reserved: number;
  is_applied: number;
}

export interface DisputeRow {
  id: string;
  workspace_id: string;
  invoice_id: string;
  reason: DisputeReason;
  status: DisputeStatus;
  disputed_amount_cents: number;
  opened_period_index: number;
  proposed_period_index: number | null;
  closed_period_index: number | null;
  seller_responded: number;
  proposed_credit_memo_id: string | null;
  created_at: string;
}

export interface DisputeItemRow {
  id: string;
  dispute_id: string;
  invoice_line_id: string;
  disputed_units: number | null;
  disputed_amount_cents: number | null;
}

export interface CreditMemoRow {
  id: string;
  workspace_id: string;
  customer_id: string;
  invoice_id: string | null;
  document_number: string | null;
  status: CreditMemoStatus;
  type: CreditMemoType;
  total_cents: number;
  applied_cents: number;
  reason: string | null;
  dispute_id: string | null;
  issued_period_index: number | null;
  is_system_generated: number;
  created_at: string;
}

export interface CreditMemoItemRow {
  id: string;
  credit_memo_id: string;
  invoice_line_id: string | null;
  description: string | null;
  quantity_units: number | null;
  unit_price_cents: number | null;
  amount_cents: number;
}

export interface CreditMemoApplicationRow {
  id: string;
  credit_memo_id: string;
  invoice_id: string;
  amount_cents: number;
  applied_at: string;
}

export interface IdempotencyKeyRow {
  workspace_id: string;
  idempotency_key: string;
  path: string;
  payload_hash: string;
  ledger_version: number;
  response: string;
  created_at: string;
}
