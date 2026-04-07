import { postAs } from './api-client';
import { expectSuccess } from './assertions';
import type { Role } from './constants';
import {
  acceptInvoice,
  activateContract,
  addInvoiceLine,
  advancePeriod,
  createContract,
  createCreditMemo,
  createCustomer,
  createDispute,
  createInvoice,
  createPurchaseOrder,
  createWorkspace,
  finalizeInvoice,
  getContractId,
  getCreditMemoId,
  getCustomerId,
  getDisputeId,
  getFirstInvoiceLineId,
  getFirstPurchaseOrderLineId,
  getInvoice,
  getInvoiceId,
  getPaymentId,
  getPurchaseOrder,
  getPurchaseOrderId,
  getWorkspace,
  issueCreditMemo,
  markPaymentCleared,
  recordReceipt,
  sendInvoice,
  uniqueId
} from './resources';

export function unwrap<T = any>(body: any): T {
  return body && typeof body === 'object' && 'data' in body ? body.data : body;
}

export async function getPolicies(workspaceId: string, role: Role) {

  const res = await postAs(`/workspaces/${workspaceId}/policies`, {}, role);
  return { res, body: unwrap(res.body) };
}

export async function postPolicies(
  workspaceId: string,
  body: any,
  role: Role,
  headers?: Record<string, string>
) {
  const res = await postAs(`/workspaces/${workspaceId}/policies`, body, role, headers);
  return { res, body: unwrap(res.body) };
}

export async function setPolicies(workspaceId: string, patch: any, role: Role = 'SellerAdmin') {
  const res = await postAs(`/workspaces/${workspaceId}/policies`, patch, role);
  expectSuccess(res, 200);
  return unwrap(res.body);
}

export type WorkspaceCustomerContractSetupParams = Partial<{
  currency: string;
  payment_terms_periods: number;
  requires_po: boolean;
  billing_cap_cents_per_period: number;
  workspaceRole: Role;
  customerRole: Role;
  contractRole: Role;
  customerOverrides: Parameters<typeof createCustomer>[1];
  contractOverrides: Parameters<typeof createContract>[2];
}>;

export async function setupWorkspaceCustomerContract(params: WorkspaceCustomerContractSetupParams = {}) {
  const workspace = await createWorkspace({ currency: params.currency ?? 'USD' }, params.workspaceRole ?? 'SellerAdmin');
  const workspaceId = workspace.workspace_id;

  const customer = await createCustomer(workspaceId, params.customerOverrides ?? {}, params.customerRole ?? 'SellerAdmin');
  const customerId = getCustomerId(customer);

  const contract = await createContract(
    workspaceId,
    customerId,
    {
      ...(params.contractOverrides ?? {}),
      ...(typeof params.payment_terms_periods === 'number' ? { payment_terms_periods: params.payment_terms_periods } : {}),
      ...(typeof params.requires_po === 'boolean' ? { requires_po: params.requires_po } : {}),
      ...(typeof params.billing_cap_cents_per_period === 'number'
        ? { billing_cap_cents_per_period: params.billing_cap_cents_per_period }
        : {})
    },
    params.contractRole ?? 'SellerAdmin'
  );
  const contractId = getContractId(contract);
  await activateContract(workspaceId, contractId, params.contractRole ?? 'SellerAdmin');

  return { workspace, customer, contract, workspaceId, customerId, contractId };
}

export async function advanceToPeriod(workspaceId: string, targetPeriodIndex: number) {
  while (true) {
    const ws = await getWorkspace(workspaceId, 'SellerAdmin');
    if (ws.period_index >= targetPeriodIndex) return;
    await advancePeriod(workspaceId, 'System');
  }
}

export async function createActiveContractId(
  workspaceId: string,
  customerId: string,
  overrides: Parameters<typeof createContract>[2]
) {
  const contract = await createContract(workspaceId, customerId, overrides, 'SellerAdmin');
  const contractId = getContractId(contract);
  await activateContract(workspaceId, contractId, 'SellerAdmin');
  return contractId;
}

export type CreateSentMatchedInvoiceParams = {
  workspaceId: string;
  customerId: string;
  contractId: string;
  orderedUnits?: number;
  invoiceUnits?: number;
  poUnitPriceCents?: number;
  invoiceUnitPriceCents?: number;
  isService?: boolean;
  receiptUnits?: number;
};

export async function createSentMatchedInvoice(params: CreateSentMatchedInvoiceParams) {
  const orderedUnits = params.orderedUnits ?? 10;
  const poUnitPriceCents = params.poUnitPriceCents ?? 10_000;
  const isService = params.isService ?? true;

  const po = await createPurchaseOrder(
    params.workspaceId,
    params.customerId,
    {
      po_number: `PO-${uniqueId('po')}`,
      lines: [{ ordered_units: orderedUnits, unit_price_cents: poUnitPriceCents, is_service: isService }]
    },
    'BuyerAP'
  );
  const poId = getPurchaseOrderId(po);
  const poFull = await getPurchaseOrder(params.workspaceId, poId, 'SellerAdmin');
  const poLineId = getFirstPurchaseOrderLineId(poFull);

  if (!isService && typeof params.receiptUnits === 'number') {
    await recordReceipt(params.workspaceId, poId, [{ purchase_order_line_id: poLineId, received_units: params.receiptUnits }], 'BuyerAP').then(
      expectSuccess
    );
  }

  const invoice = await createInvoice(
    params.workspaceId,
    params.customerId,
    {
      contract_id: params.contractId,
      purchase_order_id: poId,
      external_invoice_ref: `INV-${uniqueId('ext')}`
    },
    'SellerAR'
  );
  const invoiceId = getInvoiceId(invoice);

  await addInvoiceLine(params.workspaceId, invoiceId, {
    description: 'Line',
    quantity_units: params.invoiceUnits ?? orderedUnits,
    unit_price_cents: params.invoiceUnitPriceCents ?? poUnitPriceCents,
    purchase_order_line_id: poLineId
  });
  await finalizeInvoice(params.workspaceId, invoiceId, {}, 'SellerAR');
  await sendInvoice(params.workspaceId, invoiceId, 'SellerAR');

  return { invoiceId, poId, poLineId };
}

export async function createDraftInvoiceWithSingleLine(params: {
  workspaceId: string;
  customerId: string;
  contractId: string;
  totalCents: number;
  prefix?: string;
}) {
  const invoice = await createInvoice(
    params.workspaceId,
    params.customerId,
    { contract_id: params.contractId, external_invoice_ref: `INV-${uniqueId(params.prefix ?? 'draft')}` },
    'SellerAR'
  );
  const invoiceId = getInvoiceId(invoice);
  await addInvoiceLine(params.workspaceId, invoiceId, { description: 'Line', quantity_units: 1, unit_price_cents: params.totalCents }, 'SellerAR');
  return invoiceId;
}

export async function createAcceptedInvoice(params: {
  workspaceId: string;
  customerId: string;
  contractId: string;
  totalCents: number;
  prefix?: string;
}) {
  const invoiceId = await createDraftInvoiceWithSingleLine({
    workspaceId: params.workspaceId,
    customerId: params.customerId,
    contractId: params.contractId,
    totalCents: params.totalCents,
    prefix: params.prefix
  });
  await finalizeInvoice(params.workspaceId, invoiceId, {}, 'SellerAR');
  await sendInvoice(params.workspaceId, invoiceId, 'SellerAR');
  await acceptInvoice(params.workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);
  const inv = await getInvoice(params.workspaceId, invoiceId, 'SellerAdmin');
  expect(inv.status).toBe('ACCEPTED');
  return invoiceId;
}

export async function finalizeInvoiceWithBody(
  workspaceId: string,
  invoiceId: string,
  body: any,
  role: Role,
  headers?: Record<string, string>
) {
  return postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/finalize`, body, role, headers);
}

export async function finalizeAndSend(workspaceId: string, invoiceId: string) {
  await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
  await sendInvoice(workspaceId, invoiceId, 'SellerAR');
  return await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
}

export type CreatePoLinkedInvoiceParams = {
  workspaceId: string;
  customerId: string;
  contractId: string;
  orderedUnits?: number;
  invoiceUnits?: number;
  unitPriceCents?: number;
  receiptUnits?: number;
  isService?: boolean;
  omitPoLineLink?: boolean;
  prefix?: string;
};

export async function createPoLinkedInvoice(params: CreatePoLinkedInvoiceParams) {
  const orderedUnits = params.orderedUnits ?? 10;
  const invoiceUnits = params.invoiceUnits ?? orderedUnits;

  const unitPriceCents = params.unitPriceCents ?? 1_000;
  const isService = params.isService ?? false;

  const po = await createPurchaseOrder(
    params.workspaceId,
    params.customerId,
    { lines: [{ ordered_units: orderedUnits, unit_price_cents: unitPriceCents, is_service: isService }] },
    'BuyerAP'
  );
  const poId = getPurchaseOrderId(po);
  const poFull = await getPurchaseOrder(params.workspaceId, poId, 'SellerAdmin');
  const poLineId = getFirstPurchaseOrderLineId(poFull);

  if (typeof params.receiptUnits === 'number') {
    const receiptRes = await recordReceipt(params.workspaceId, poId, [{ purchase_order_line_id: poLineId, received_units: params.receiptUnits }], 'BuyerAP');
    expectSuccess(receiptRes);
  }

  const invoice = await createInvoice(
    params.workspaceId,
    params.customerId,
    { contract_id: params.contractId, purchase_order_id: poId, external_invoice_ref: `INV-${uniqueId(params.prefix ?? 'po')}` },
    'SellerAR'
  );
  const invoiceId = getInvoiceId(invoice);

  await addInvoiceLine(
    params.workspaceId,
    invoiceId,
    {
      description: 'Line',
      quantity_units: invoiceUnits,
      unit_price_cents: unitPriceCents,
      purchase_order_line_id: params.omitPoLineLink ? undefined : poLineId
    },
    'SellerAR'
  );

  return { invoiceId, poId, poLineId };
}

export async function createSentExceptionInvoice(params: {
  workspaceId: string;
  customerId: string;
  contractId: string;
  receiptUnits?: number;
  orderedUnits?: number;
  invoiceUnits?: number;
  unitPriceCents?: number;
  prefix?: string;
}) {
  const { invoiceId, poId, poLineId } = await createPoLinkedInvoice({
    workspaceId: params.workspaceId,
    customerId: params.customerId,
    contractId: params.contractId,
    orderedUnits: params.orderedUnits ?? 10,
    invoiceUnits: params.invoiceUnits ?? (params.orderedUnits ?? 10),
    unitPriceCents: params.unitPriceCents ?? 1_000,
    isService: false,
    receiptUnits: params.receiptUnits,
    prefix: params.prefix
  });
  const sent = await finalizeAndSend(params.workspaceId, invoiceId);
  expect(sent.status).toBe('SENT');
  expect(sent.purchase_order_id).toBeTruthy();
  expect(sent.match_status).toBe('EXCEPTION');
  return { invoiceId, poId, poLineId, sentInvoice: sent };
}

export async function createSentMatchedPoInvoice(params: { workspaceId: string; customerId: string; contractId: string }) {
  const { invoiceId } = await createPoLinkedInvoice({
    workspaceId: params.workspaceId,
    customerId: params.customerId,
    contractId: params.contractId,
    orderedUnits: 10,
    invoiceUnits: 10,
    unitPriceCents: 1_000,
    isService: true
  });
  const sent = await finalizeAndSend(params.workspaceId, invoiceId);
  expect(sent.status).toBe('SENT');
  expect(sent.match_status).toBe('MATCHED');
  return { invoiceId, sentInvoice: sent };
}

export async function createPoExceptionInvoice(params: {
  workspaceId: string;
  customerId: string;
  contractId: string;
  orderedUnits?: number;
  invoiceUnits?: number;
  unitPriceCents?: number;
  receiptUnits?: number;
  prefix?: string;
}) {
  const orderedUnits = params.orderedUnits ?? 10;
  const invoiceUnits = params.invoiceUnits ?? orderedUnits;
  const unitPriceCents = params.unitPriceCents ?? 1_000;

  const po = await createPurchaseOrder(
    params.workspaceId,
    params.customerId,
    { lines: [{ ordered_units: orderedUnits, unit_price_cents: unitPriceCents, is_service: false }] },
    'BuyerAP'
  );
  const poId = getPurchaseOrderId(po);
  const poFull = await getPurchaseOrder(params.workspaceId, poId, 'SellerAdmin');
  const poLineId = getFirstPurchaseOrderLineId(poFull);

  if (typeof params.receiptUnits === 'number') {
    const receiptRes = await postAs(
      `/workspaces/${params.workspaceId}/purchase_orders/${poId}/record_receipt`,
      { items: [{ purchase_order_line_id: poLineId, received_units: params.receiptUnits }] },
      'BuyerAP'
    );
    expectSuccess(receiptRes);
  }

  const invoice = await createInvoice(
    params.workspaceId,
    params.customerId,
    { contract_id: params.contractId, purchase_order_id: poId, external_invoice_ref: `INV-${uniqueId(params.prefix ?? 'po-exc')}` },
    'SellerAR'
  );
  const invoiceId = getInvoiceId(invoice);

  await addInvoiceLine(
    params.workspaceId,
    invoiceId,
    { description: 'Line', quantity_units: invoiceUnits, unit_price_cents: unitPriceCents, purchase_order_line_id: poLineId },
    'SellerAR'
  );

  await finalizeInvoice(params.workspaceId, invoiceId, {}, 'SellerAR');
  await sendInvoice(params.workspaceId, invoiceId, 'SellerAR');

  const sent = await getInvoice(params.workspaceId, invoiceId, 'SellerAdmin');
  expect(sent.status).toBe('SENT');
  expect(sent.purchase_order_id).toBe(poId);
  expect(sent.match_status).toBe('EXCEPTION');

  return { invoiceId, poId, poLineId };
}

export async function createSentInvoiceWithDispute(params: {
  workspaceId: string;
  customerId: string;
  contractId: string;
  totalCents: number;
  disputedCents: number;
  prefix?: string;
}) {
  const invoice = await createInvoice(
    params.workspaceId,
    params.customerId,
    { contract_id: params.contractId, external_invoice_ref: `INV-${uniqueId(params.prefix ?? 'disp')}` },
    'SellerAR'
  );
  const invoiceId = getInvoiceId(invoice);
  await addInvoiceLine(params.workspaceId, invoiceId, { description: 'Line', quantity_units: 1, unit_price_cents: params.totalCents }, 'SellerAR');
  await finalizeInvoice(params.workspaceId, invoiceId, {}, 'SellerAR');
  await sendInvoice(params.workspaceId, invoiceId, 'SellerAR');

  const inv = await getInvoice(params.workspaceId, invoiceId, 'SellerAdmin');
  const lineId = getFirstInvoiceLineId(inv);

  const dispute = await createDispute(
    params.workspaceId,
    invoiceId,
    { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: params.disputedCents }] },
    'BuyerAP'
  );
  const disputeId = getDisputeId(dispute);

  return { invoiceId, disputeId, lineId };
}

export async function createAcceptedInvoiceWithDispute(params: {
  workspaceId: string;
  customerId: string;
  contractId: string;
  totalCents: number;
  disputedCents: number;
  prefix?: string;
}) {
  const invoice = await createInvoice(
    params.workspaceId,
    params.customerId,
    { contract_id: params.contractId, external_invoice_ref: `INV-${uniqueId(params.prefix ?? 'acc-disp')}` },
    'SellerAR'
  );
  const invoiceId = getInvoiceId(invoice);
  await addInvoiceLine(params.workspaceId, invoiceId, { description: 'Line', quantity_units: 1, unit_price_cents: params.totalCents }, 'SellerAR');
  await finalizeInvoice(params.workspaceId, invoiceId, {}, 'SellerAR');
  await sendInvoice(params.workspaceId, invoiceId, 'SellerAR');
  await acceptInvoice(params.workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

  const inv = await getInvoice(params.workspaceId, invoiceId, 'SellerAdmin');
  expect(inv.status).toBe('ACCEPTED');
  const lineId = getFirstInvoiceLineId(inv);

  const dispute = await createDispute(
    params.workspaceId,
    invoiceId,
    { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: params.disputedCents }] },
    'BuyerAP'
  );
  const disputeId = getDisputeId(dispute);

  return { invoiceId, disputeId, lineId };
}

export async function createWaiver(
  workspaceId: string,
  invoiceId: string,
  body: any = {},
  headers?: Record<string, string>
) {
  const res = await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/waive_match_exceptions`, body, 'BuyerAP', headers);
  expectSuccess(res);
  return unwrap(res.body);
}

export async function revokeWaiver(workspaceId: string, invoiceId: string, headers?: Record<string, string>) {
  return postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/revoke_match_waiver`, {}, 'BuyerAP', headers);
}

export async function createEscrowPayment(params: {
  workspaceId: string;
  customerId: string;
  invoiceId: string;
  escrowCents: number;
  role?: Role;
}) {
  const res = await postAs(
    `/workspaces/${params.workspaceId}/customers/${params.customerId}/payments`,
    {
      amount_cents: params.escrowCents,
      allocations: [{ invoice_id: params.invoiceId, amount_cents: params.escrowCents, is_escrow: true }]
    },
    params.role ?? 'BuyerAP'
  );
  return res;
}

export async function createEscrowPaymentAndReturn(params: {
  workspaceId: string;
  customerId: string;
  invoiceId: string;
  escrowCents: number;
  role?: Role;
}) {
  const res = await createEscrowPayment(params);
  expectSuccess(res, 201);
  return unwrap(res.body);
}

export async function issueUntiedCreditMemo(params: {
  workspaceId: string;
  customerId: string;
  totalCents: number;
  role?: Role;
  invoiceLineId?: string;
  quantityUnits?: number;
  unitPriceCents?: number;
}) {
  const cm = await createCreditMemo(
    params.workspaceId,
    params.customerId,
    {
      reason: 'GOODWILL',
      items: [
        params.invoiceLineId
          ? { invoice_line_id: params.invoiceLineId, quantity_units: params.quantityUnits ?? 1, unit_price_cents: params.unitPriceCents ?? params.totalCents }
          : { quantity_units: 1, unit_price_cents: params.totalCents }
      ]
    },
    params.role ?? 'SellerAdmin'
  );
  const cmId = getCreditMemoId(cm);
  await issueCreditMemo(params.workspaceId, cmId, params.role ?? 'SellerAdmin');
  return { cmId };
}

export async function issueInvoiceTiedCreditMemo(params: {
  workspaceId: string;
  customerId: string;
  invoiceId: string;
  items: any[];
  role?: Role;
}) {
  const cm = await createCreditMemo(
    params.workspaceId,
    params.customerId,
    { invoice_id: params.invoiceId, reason: 'GOODWILL', items: params.items },
    params.role ?? 'SellerAdmin'
  );
  const cmId = getCreditMemoId(cm);
  await issueCreditMemo(params.workspaceId, cmId, params.role ?? 'SellerAdmin');
  return { cmId };
}

export async function runSettlement(
  workspaceId: string,
  body: any = {},
  role: Role = 'SellerAdmin',
  headers?: Record<string, string>
) {
  return postAs(`/workspaces/${workspaceId}/run_settlement`, body, role, headers);
}

export async function createClearedPaymentWithNoEligibleInvoices(params: {
  workspaceId: string;
  customerId: string;
  amountCents: number;
  role?: Role;
}) {
  const res = await postAs(
    `/workspaces/${params.workspaceId}/customers/${params.customerId}/payments`,
    { amount_cents: params.amountCents, allocations: [] },
    params.role ?? 'BuyerAP'
  );
  expectSuccess(res, 201);
  const paymentId = getPaymentId(unwrap(res.body));
  await markPaymentCleared(params.workspaceId, paymentId, 'SellerAdmin');
  return paymentId;
}

export async function createUnappliedCashPayment(
  workspaceId: string,
  customerId: string,
  amountCents: number,
  allocation?: { invoiceId: string; cents: number }
) {
  const body = allocation
    ? { amount_cents: amountCents, allocations: [{ invoice_id: allocation.invoiceId, amount_cents: allocation.cents }] }
    : { amount_cents: amountCents, allocations: [] };
  const res = await postAs(`/workspaces/${workspaceId}/customers/${customerId}/payments`, body, 'BuyerAP');
  expectSuccess(res, 201);
  const paymentId = getPaymentId(unwrap(res.body));
  await markPaymentCleared(workspaceId, paymentId, 'SellerAdmin');
  return paymentId;
}

export function sumAppliedAllocations(payment: any): number {
  const allocations = payment?.allocations;
  if (!Array.isArray(allocations)) return 0;
  return allocations
    .filter((a: any) => a && a.is_applied === true && a.is_escrow !== true)
    .reduce((sum: number, a: any) => sum + (a.amount_cents ?? 0), 0);
}
