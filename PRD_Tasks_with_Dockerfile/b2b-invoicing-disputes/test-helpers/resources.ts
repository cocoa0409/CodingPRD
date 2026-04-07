import { v4 as uuidv4 } from 'uuid';
import { getAs, postAs } from './api-client';
import { expectSuccess } from './assertions';
import { DEFAULT_CURRENCY, Role } from './constants';
import { trackCustomer, trackWorkspace } from './ledger-scope';

export function uniqueId(prefix: string = 'test'): string {
  return `${prefix}-${uuidv4().slice(0, 8)}`;
}

function unwrap<T = any>(body: any): T {
  return (body && typeof body === 'object' && 'data' in body) ? body.data : body;
}

function pickId(body: any, keys: string[]): string {
  for (const key of keys) {
    const value = body?.[key];
    if (typeof value === 'string' && value.length > 0) return value;
  }
  throw new Error(`Could not find id in response. Looked for: ${keys.join(', ')}`);
}

export async function createWorkspace(
  overrides: Partial<{ name: string; currency: string }> = {},
  role: Role = 'SellerAdmin'
) {
  const res = await postAs(
    '/workspaces',
    { name: overrides.name ?? `Workspace-${uniqueId('ws')}`, currency: overrides.currency ?? DEFAULT_CURRENCY },
    role
  );
  expectSuccess(res);
  const data = unwrap(res.body);
  const workspace = data as {
    workspace_id: string;
    currency: string;
    period_index: number;
    books_closed_through_period_index: number | null;
  };

  trackWorkspace(workspace.workspace_id);
  return workspace;
}

export async function getWorkspace(workspaceId: string, role: Role = 'SellerAdmin') {
  const res = await getAs(`/workspaces/${workspaceId}`, role);
  expectSuccess(res);
  return unwrap(res.body);
}

export async function advancePeriod(workspaceId: string, role: Role = 'System') {
  const res = await postAs(`/workspaces/${workspaceId}/advance_period`, {}, role);
  expectSuccess(res);
  return unwrap(res.body);
}

export async function closeBooks(workspaceId: string, role: Role = 'Auditor') {
  return postAs(`/workspaces/${workspaceId}/close_books`, {}, role);
}

export async function recompute(workspaceId: string, role: Role = 'SellerAdmin') {
  const res = await postAs(`/workspaces/${workspaceId}/recompute`, {}, role);
  return res;
}

export async function createCustomer(
  workspaceId: string,
  overrides: Partial<{ display_name: string; external_customer_ref: string; credit_limit_cents: number }> = {},
  role: Role = 'SellerAdmin'
) {
  const res = await postAs(
    `/workspaces/${workspaceId}/customers`,
    {
      display_name: overrides.display_name ?? `Customer-${uniqueId('cust')}`,
      external_customer_ref: overrides.external_customer_ref ?? `CUST-${uniqueId('ref')}`,
      credit_limit_cents: overrides.credit_limit_cents ?? 5_000_000
    },
    role
  );
  expectSuccess(res);
  const data = unwrap(res.body);

  try {
    const customerId = pickId(data, ['customer_id', 'id']);
    trackCustomer(workspaceId, customerId);
  } catch {

  }
  return data as any;
}

export async function getCustomer(workspaceId: string, customerId: string, role: Role = 'SellerAdmin') {
  const res = await getAs(`/workspaces/${workspaceId}/customers/${customerId}`, role);
  expectSuccess(res);
  return unwrap(res.body) as any;
}

export async function freezeCustomer(workspaceId: string, customerId: string, reason: string = 'MANUAL', role: Role = 'SellerAdmin') {
  const res = await postAs(`/workspaces/${workspaceId}/customers/${customerId}/freeze`, { reason }, role);
  return res;
}

export async function unfreezeCustomer(workspaceId: string, customerId: string, role: Role = 'SellerAdmin') {
  const res = await postAs(`/workspaces/${workspaceId}/customers/${customerId}/unfreeze`, {}, role);
  return res;
}

export async function closeCustomer(workspaceId: string, customerId: string, role: Role = 'SellerAdmin') {
  const res = await postAs(`/workspaces/${workspaceId}/customers/${customerId}/close`, {}, role);
  return res;
}

export async function createContract(
  workspaceId: string,
  customerId: string,
  overrides: Partial<{
    name: string;
    payment_terms_periods: number;
    requires_po: boolean;
    billing_cap_cents_per_period: number;
  }> = {},
  role: Role = 'SellerAdmin'
) {
  const res = await postAs(
    `/workspaces/${workspaceId}/customers/${customerId}/contracts`,
    {
      name: overrides.name ?? `Contract-${uniqueId('ctr')}`,
      payment_terms_periods: overrides.payment_terms_periods ?? 2,
      requires_po: overrides.requires_po ?? false,
      billing_cap_cents_per_period: overrides.billing_cap_cents_per_period ?? 10_000_000
    },
    role
  );
  expectSuccess(res);
  return unwrap(res.body) as any;
}

export async function activateContract(workspaceId: string, contractId: string, role: Role = 'SellerAdmin') {
  const res = await postAs(`/workspaces/${workspaceId}/contracts/${contractId}/activate`, {}, role);
  expectSuccess(res);
  return unwrap(res.body);
}

export async function suspendContract(workspaceId: string, contractId: string, role: Role = 'SellerAdmin') {
  const res = await postAs(`/workspaces/${workspaceId}/contracts/${contractId}/suspend`, {}, role);
  expectSuccess(res);
  return unwrap(res.body);
}

export async function terminateContract(workspaceId: string, contractId: string, role: Role = 'SellerAdmin') {
  const res = await postAs(`/workspaces/${workspaceId}/contracts/${contractId}/terminate`, {}, role);
  expectSuccess(res);
  return unwrap(res.body);
}

export async function getContract(workspaceId: string, contractId: string, role: Role = 'SellerAdmin') {
  const res = await getAs(`/workspaces/${workspaceId}/contracts/${contractId}`, role);
  expectSuccess(res);
  return unwrap(res.body) as any;
}

export async function createPurchaseOrder(
  workspaceId: string,
  customerId: string,
  params: {
    po_number?: string;
    lines: Array<{ description?: string; ordered_units: number; unit_price_cents: number; is_service: boolean }>;
  },
  role: Role = 'BuyerAP'
) {
  const res = await postAs(
    `/workspaces/${workspaceId}/customers/${customerId}/purchase_orders`,
    {
      po_number: params.po_number ?? `PO-${uniqueId('po')}`,
      lines: params.lines.map((l) => ({
        description: l.description ?? `Line-${uniqueId('pol')}`,
        ordered_units: l.ordered_units,
        unit_price_cents: l.unit_price_cents,
        is_service: l.is_service
      }))
    },
    role
  );
  expectSuccess(res);
  return unwrap(res.body) as any;
}

export async function getPurchaseOrder(workspaceId: string, purchaseOrderId: string, role: Role = 'SellerAdmin') {
  const res = await getAs(`/workspaces/${workspaceId}/purchase_orders/${purchaseOrderId}`, role);
  expectSuccess(res);
  return unwrap(res.body) as any;
}

export async function acknowledgePurchaseOrder(workspaceId: string, purchaseOrderId: string, role: Role = 'SellerAR') {
  const res = await postAs(`/workspaces/${workspaceId}/purchase_orders/${purchaseOrderId}/acknowledge`, {}, role);
  expectSuccess(res);
  return unwrap(res.body) as any;
}

export async function cancelPurchaseOrder(workspaceId: string, purchaseOrderId: string, role: Role = 'BuyerAP') {
  const res = await postAs(`/workspaces/${workspaceId}/purchase_orders/${purchaseOrderId}/cancel`, {}, role);
  return res;
}

export async function closePurchaseOrder(workspaceId: string, purchaseOrderId: string, role: Role = 'BuyerAP') {
  const res = await postAs(`/workspaces/${workspaceId}/purchase_orders/${purchaseOrderId}/close`, {}, role);
  return res;
}

export async function recordReceipt(
  workspaceId: string,
  purchaseOrderId: string,
  items: Array<{ purchase_order_line_id: string; received_units: number }>,
  role: Role = 'BuyerAP'
) {
  const res = await postAs(`/workspaces/${workspaceId}/purchase_orders/${purchaseOrderId}/record_receipt`, { items }, role);
  return res;
}

export async function createInvoice(
  workspaceId: string,
  customerId: string,
  params: { contract_id: string; purchase_order_id?: string; external_invoice_ref?: string },
  role: Role = 'SellerAR'
) {
  const res = await postAs(
    `/workspaces/${workspaceId}/customers/${customerId}/invoices`,
    {
      contract_id: params.contract_id,
      purchase_order_id: params.purchase_order_id,
      external_invoice_ref: params.external_invoice_ref ?? `INV-${uniqueId('ext')}`
    },
    role
  );
  expectSuccess(res);
  return unwrap(res.body) as any;
}

export async function addInvoiceLine(
  workspaceId: string,
  invoiceId: string,
  params: { description?: string; quantity_units: number; unit_price_cents: number; purchase_order_line_id?: string },
  role: Role = 'SellerAR'
) {
  const res = await postAs(
    `/workspaces/${workspaceId}/invoices/${invoiceId}/lines`,
    {
      description: params.description ?? `Item-${uniqueId('line')}`,
      quantity_units: params.quantity_units,
      unit_price_cents: params.unit_price_cents,
      purchase_order_line_id: params.purchase_order_line_id
    },
    role
  );
  expectSuccess(res);
  const data = unwrap(res.body);
  return data as any;
}

export async function finalizeInvoice(
  workspaceId: string,
  invoiceId: string,
  params: Partial<{ override_hold: boolean; override_billing_cap: boolean; override_credit_limit: boolean; final_invoice: boolean }> = {},
  role: Role = 'SellerAR'
) {
  const body: Record<string, unknown> = {
    override_hold: params.override_hold ?? false,
    override_billing_cap: params.override_billing_cap ?? false,
    final_invoice: params.final_invoice ?? false
  };
  if (params.override_credit_limit !== undefined) {
    body.override_credit_limit = params.override_credit_limit;
  }
  const res = await postAs(
    `/workspaces/${workspaceId}/invoices/${invoiceId}/finalize`,
    body,
    role
  );
  expectSuccess(res);
  return unwrap(res.body) as any;
}

export async function sendInvoice(workspaceId: string, invoiceId: string, role: Role = 'SellerAR') {
  const res = await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, role);
  expectSuccess(res);
  return unwrap(res.body) as any;
}

export async function acceptInvoice(workspaceId: string, invoiceId: string, role: Role = 'BuyerAP') {
  return postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/accept`, {}, role);
}

export async function voidInvoice(workspaceId: string, invoiceId: string, role: Role = 'SellerAR') {
  return postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/void`, {}, role);
}

export async function getInvoice(workspaceId: string, invoiceId: string, role: Role = 'SellerAdmin') {
  const res = await getAs(`/workspaces/${workspaceId}/invoices/${invoiceId}`, role);
  expectSuccess(res);
  return unwrap(res.body) as any;
}

export async function listInvoices(
  workspaceId: string,
  query: Partial<{ customer_id: string; status: string; type: string }> = {},
  role: Role = 'SellerAdmin'
) {
  const qs = new URLSearchParams();
  Object.entries(query).forEach(([k, v]) => {
    if (typeof v === 'string' && v.length > 0) qs.set(k, v);
  });
  const path = qs.toString().length > 0 ? `/workspaces/${workspaceId}/invoices?${qs.toString()}` : `/workspaces/${workspaceId}/invoices`;

  const res = await getAs(path, role);
  expectSuccess(res);
  const data = unwrap(res.body);

  if (Array.isArray(data)) return data;
  if (Array.isArray(data?.invoices)) return data.invoices;
  if (Array.isArray(data?.items)) return data.items;
  if (Array.isArray(data?.data)) return data.data;
  if (data && typeof data === 'object') {
    const values = Object.values(data);
    if (
      values.length > 0 &&
      values.every((v) => v && typeof v === 'object') &&
      values.some((v: any) => typeof v?.invoice_id === 'string' || typeof v?.id === 'string')
    ) {
      return values as any[];
    }
  }

  throw new Error('Unexpected listInvoices response shape');
}

export async function createDispute(
  workspaceId: string,
  invoiceId: string,
  params: { reason: string; items: Array<{ invoice_line_id: string; disputed_units?: number; disputed_amount_cents?: number }> },
  role: Role = 'BuyerAP'
) {
  const res = await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/disputes`, params, role);
  expectSuccess(res);
  return unwrap(res.body) as any;
}

export async function getDispute(workspaceId: string, disputeId: string, role: Role = 'SellerAdmin') {
  const res = await getAs(`/workspaces/${workspaceId}/disputes/${disputeId}`, role);
  expectSuccess(res);
  return unwrap(res.body) as any;
}

export async function sellerRespond(workspaceId: string, disputeId: string, role: Role = 'SellerAR') {
  const res = await postAs(`/workspaces/${workspaceId}/disputes/${disputeId}/seller_respond`, {}, role);
  expectSuccess(res);
  return unwrap(res.body) as any;
}

export async function proposeResolution(
  workspaceId: string,
  disputeId: string,
  body: any,
  role: Role = 'SellerAR'
) {
  const res = await postAs(`/workspaces/${workspaceId}/disputes/${disputeId}/propose_resolution`, body, role);
  expectSuccess(res);
  return unwrap(res.body) as any;
}

export async function acceptResolution(workspaceId: string, disputeId: string, role: Role = 'BuyerAP') {
  const res = await postAs(`/workspaces/${workspaceId}/disputes/${disputeId}/accept_resolution`, {}, role);
  return res;
}

export async function rejectResolution(workspaceId: string, disputeId: string, role: Role = 'BuyerAP') {
  const res = await postAs(`/workspaces/${workspaceId}/disputes/${disputeId}/reject_resolution`, {}, role);
  return res;
}

export async function createPayment(
  workspaceId: string,
  customerId: string,
  body: { amount_cents: number; allocations?: Array<{ invoice_id: string; amount_cents: number }> },
  role: Role = 'BuyerAP'
) {
  const res = await postAs(`/workspaces/${workspaceId}/customers/${customerId}/payments`, body, role);
  expectSuccess(res);
  return unwrap(res.body) as any;
}

export async function markPaymentCleared(workspaceId: string, paymentId: string, role: Role = 'SellerAR') {
  const res = await postAs(`/workspaces/${workspaceId}/payments/${paymentId}/mark_cleared`, {}, role);
  expectSuccess(res);
  return unwrap(res.body) as any;
}

export async function markPaymentFailed(workspaceId: string, paymentId: string, role: Role = 'SellerAR') {
  const res = await postAs(`/workspaces/${workspaceId}/payments/${paymentId}/mark_failed`, {}, role);
  expectSuccess(res);
  return unwrap(res.body) as any;
}

export async function getPayment(workspaceId: string, paymentId: string, role: Role = 'SellerAdmin') {
  const res = await getAs(`/workspaces/${workspaceId}/payments/${paymentId}`, role);
  expectSuccess(res);
  return unwrap(res.body) as any;
}

export async function reversePayment(workspaceId: string, paymentId: string, role: Role = 'SellerAdmin') {
  const res = await postAs(`/workspaces/${workspaceId}/payments/${paymentId}/reverse`, {}, role);
  return res;
}

export async function getCreditMemo(workspaceId: string, creditMemoId: string, role: Role = 'SellerAdmin') {
  const res = await getAs(`/workspaces/${workspaceId}/credit_memos/${creditMemoId}`, role);
  expectSuccess(res);
  return unwrap(res.body) as any;
}

export async function listCreditMemos(
  workspaceId: string,
  params: Partial<{ customer_id: string; status: string }> = {},
  role: Role = 'SellerAdmin'
) {
  const query = new URLSearchParams();
  if (params.customer_id) query.set('customer_id', params.customer_id);
  if (params.status) query.set('status', params.status);
  const qs = query.toString();
  const path = `/workspaces/${workspaceId}/credit_memos${qs ? `?${qs}` : ''}`;
  const res = await getAs(path, role);
  expectSuccess(res);
  const raw = unwrap(res.body);
  if (Array.isArray(raw)) return raw as any[];
  if (Array.isArray(raw?.items)) return raw.items as any[];
  if (Array.isArray(raw?.credit_memos)) return raw.credit_memos as any[];
  return [];
}

export async function createCreditMemo(
  workspaceId: string,
  customerId: string,
  body: { invoice_id?: string; reason: string; items: Array<Record<string, any>> },
  role: Role = 'SellerAR'
) {
  const res = await postAs(`/workspaces/${workspaceId}/customers/${customerId}/credit_memos`, body, role);
  expectSuccess(res);
  return unwrap(res.body) as any;
}

export async function issueCreditMemo(workspaceId: string, creditMemoId: string, role: Role = 'SellerAR') {
  const res = await postAs(`/workspaces/${workspaceId}/credit_memos/${creditMemoId}/issue`, {}, role);
  expectSuccess(res);
  return unwrap(res.body) as any;
}

export async function applyCreditMemo(workspaceId: string, creditMemoId: string, invoiceId: string, role: Role = 'SellerAR') {
  const res = await postAs(`/workspaces/${workspaceId}/credit_memos/${creditMemoId}/apply`, { invoice_id: invoiceId }, role);
  expectSuccess(res);
  return unwrap(res.body) as any;
}

export async function voidCreditMemo(workspaceId: string, creditMemoId: string, role: Role = 'SellerAR') {
  return postAs(`/workspaces/${workspaceId}/credit_memos/${creditMemoId}/void`, {}, role);
}

export async function writeOffInvoice(workspaceId: string, invoiceId: string, role: Role = 'SellerAR') {
  const res = await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/write_off`, {}, role);
  return res;
}

export async function withdrawDispute(workspaceId: string, disputeId: string, role: Role = 'BuyerAP') {
  const res = await postAs(`/workspaces/${workspaceId}/disputes/${disputeId}/withdraw`, {}, role);
  expectSuccess(res);
  return unwrap(res.body) as any;
}

export function getCustomerId(customer: any): string {
  return pickId(customer, ['customer_id', 'id']);
}

export function getContractId(contract: any): string {
  return pickId(contract, ['contract_id', 'id']);
}

export function getPurchaseOrderId(po: any): string {
  return pickId(po, ['purchase_order_id', 'id']);
}

export function getInvoiceId(invoice: any): string {
  return pickId(invoice, ['invoice_id', 'id']);
}

export function getDisputeId(dispute: any): string {
  return pickId(dispute, ['dispute_id', 'id']);
}

export function getPaymentId(payment: any): string {
  return pickId(payment, ['payment_id', 'id']);
}

export function getCreditMemoId(creditMemo: any): string {
  return pickId(creditMemo, ['credit_memo_id', 'id']);
}

export function getFirstPurchaseOrderLineId(po: any): string {
  const lines = po?.lines;
  if (!Array.isArray(lines) || lines.length === 0) throw new Error('purchase order has no lines');
  return pickId(lines[0], ['purchase_order_line_id', 'id', 'line_id']);
}

export function getFirstInvoiceLineId(invoice: any): string {
  const lines = invoice?.lines;
  if (!Array.isArray(lines) || lines.length === 0) throw new Error('invoice has no lines');
  return pickId(lines[0], ['invoice_line_id', 'id', 'line_id']);
}
