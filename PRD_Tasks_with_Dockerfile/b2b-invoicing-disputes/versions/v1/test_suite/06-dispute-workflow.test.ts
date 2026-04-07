import { postAs } from '../../../test-helpers/api-client';
import { expectErrorCode, expectSuccess } from '../../../test-helpers/assertions';
import { advanceToPeriod, createSentMatchedInvoice, setupWorkspaceCustomerContract } from '../../../test-helpers/fixtures';
import {
  acceptResolution,
  acceptInvoice,
  activateContract,
  addInvoiceLine,
  advancePeriod,
  applyCreditMemo,
  createContract,
  createCreditMemo,
  createCustomer,
  createDispute,
  createInvoice,
  createPayment,
  createPurchaseOrder,
  createWorkspace,
  finalizeInvoice,
  getContractId,
  getCreditMemo,
  getCreditMemoId,
  getCustomer,
  getCustomerId,
  getDispute,
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
  listCreditMemos,
  markPaymentCleared,
  proposeResolution,
  rejectResolution,
  reversePayment,
  recordReceipt,
  sellerRespond,
  voidInvoice,
  withdrawDispute,
  writeOffInvoice,
  uniqueId
} from '../../../test-helpers/resources';

function asArray(maybe: any): any[] {
  if (Array.isArray(maybe)) return maybe;
  if (Array.isArray(maybe?.credit_memos)) return maybe.credit_memos;
  if (Array.isArray(maybe?.items)) return maybe.items;
  return [];
}

describe('Dispute Workflow Tests', () => {
  async function createAcceptedInvoiceNoPO(params: { workspaceId: string; customerId: string; contractId: string; totalCents: number; units: number; unitPriceCents: number }) {
    const invoice = await createInvoice(params.workspaceId, params.customerId, { contract_id: params.contractId, external_invoice_ref: `INV-${uniqueId('ext')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(params.workspaceId, invoiceId, { description: 'Line', quantity_units: params.units, unit_price_cents: params.unitPriceCents }, 'SellerAR');
    await finalizeInvoice(params.workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${params.workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(params.workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);
    const inv = await getInvoice(params.workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.amount_due_cents).toBe(params.totalCents);
    return invoiceId;
  }

  async function freezeCustomerViaReversal(workspaceId: string, customerId: string) {
    const pay = await createPayment(workspaceId, customerId, { amount_cents: 10_000 }, 'BuyerAP');
    const payId = getPaymentId(pay);
    await markPaymentCleared(workspaceId, payId, 'SellerAR');
    await reversePayment(workspaceId, payId, 'SellerAdmin').then(expectSuccess);
    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('FROZEN');
  }

  test('DSP_001: buyer can open dispute on SENT+MATCHED invoice; invoice amount_disputed_cents increases', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: true });
    const { invoiceId } = await createSentMatchedInvoice({
      workspaceId,
      customerId,
      contractId,
      orderedUnits: 10,
      invoiceUnits: 10,
      poUnitPriceCents: 10_000,
      isService: true
    });

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.status).toBe('SENT');
    expect(inv0.match_status).toBe('MATCHED');
    expect(inv0.amount_disputed_cents).toBe(0);

    const invoiceLineId = getFirstInvoiceLineId(inv0);
    const dispute = await createDispute(workspaceId, invoiceId, { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_units: 1 }] }, 'BuyerAP');
    expect(dispute.status).toBe('OPEN');

    const inv1 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv1.amount_disputed_cents).toBeGreaterThan(0);
  });

  test('DSP_002: customer frozen blocks BuyerAP disputes (ERR_CUSTOMER_FROZEN)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: true });
    const { invoiceId } = await createSentMatchedInvoice({
      workspaceId,
      customerId,
      contractId,
      orderedUnits: 10,
      invoiceUnits: 10,
      poUnitPriceCents: 10_000,
      isService: true
    });

    await freezeCustomerViaReversal(workspaceId, customerId);

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);
    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/disputes`,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_units: 1 }] },
      'BuyerAP'
    );
    await expectErrorCode(res, 'ERR_CUSTOMER_FROZEN');

    const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter.amount_disputed_cents).toBe(0);
  });

  test('DSP_003: cannot dispute a VOIDED invoice (ERR_INVOICE_NOT_DISPUTABLE)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { description: 'Line', quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
    const invWithLine = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(invWithLine);
    await voidInvoice(workspaceId, invoiceId, 'SellerAR').then(expectSuccess);

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/disputes`,
      { reason: 'DUPLICATE_INVOICE', items: [{ invoice_line_id: invoiceLineId, disputed_units: 1 }] },
      'BuyerAP'
    );
    await expectErrorCode(res, 'ERR_INVOICE_NOT_DISPUTABLE');

    const got = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(got.status).toBe('VOIDED');
  });

  test('DSP_006: cannot open second dispute while first is active (ERR_DISPUTE_ALREADY_ACTIVE)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoiceNoPO({ workspaceId, customerId, contractId, totalCents: 10_000, units: 1, unitPriceCents: 10_000 });

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);
    await createDispute(workspaceId, invoiceId, { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_amount_cents: 2000 }] }, 'BuyerAP');

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/disputes`,
      { reason: 'PRICE_MISMATCH', items: [{ invoice_line_id: invoiceLineId, disputed_amount_cents: 1000 }] },
      'BuyerAP'
    );
    await expectErrorCode(res, 'ERR_DISPUTE_ALREADY_ACTIVE');
  });

  test('DSP_007: seller_respond moves dispute OPEN -> IN_REVIEW', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoiceNoPO({ workspaceId, customerId, contractId, totalCents: 10_000, units: 1, unitPriceCents: 10_000 });
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);
    const dispute = await createDispute(workspaceId, invoiceId, { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_amount_cents: 2000 }] }, 'BuyerAP');
    const disputeId = getDisputeId(dispute);

    const updated = await sellerRespond(workspaceId, disputeId, 'SellerAR');
    expect(updated.status).toBe('IN_REVIEW');
  });

  test('DSP_008: withdraw sets dispute WITHDRAWN and releases invoice amount_disputed_cents', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoiceNoPO({ workspaceId, customerId, contractId, totalCents: 10_000, units: 1, unitPriceCents: 10_000 });
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);
    const dispute = await createDispute(workspaceId, invoiceId, { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_amount_cents: 3000 }] }, 'BuyerAP');
    const disputeId = getDisputeId(dispute);
    await sellerRespond(workspaceId, disputeId, 'SellerAR');

    const before = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(before.amount_disputed_cents).toBe(3000);

    const withdrawn = await withdrawDispute(workspaceId, disputeId, 'BuyerAP');
    expect(withdrawn.status).toBe('WITHDRAWN');

    const after = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(after.amount_disputed_cents).toBeLessThan(before.amount_disputed_cents as number);
  });

  test('DSP_010: escalated disputes put customer on CREDIT_HOLD', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoiceNoPO({ workspaceId, customerId, contractId, totalCents: 10_000, units: 1, unitPriceCents: 10_000 });
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);
    await createDispute(workspaceId, invoiceId, { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_amount_cents: 1000 }] }, 'BuyerAP');
    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('CREDIT_HOLD');
  });

  test('DSP_013: propose_resolution moves dispute to PROPOSED and creates draft credit memo', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoiceNoPO({ workspaceId, customerId, contractId, totalCents: 50_000, units: 5, unitPriceCents: 10_000 });
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);
    const dispute = await createDispute(workspaceId, invoiceId, { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_amount_cents: 10_000 }] }, 'BuyerAP');
    const disputeId = getDisputeId(dispute);

    await proposeResolution(
      workspaceId,
      disputeId,
      { proposed_credit: { items: [{ invoice_line_id: invoiceLineId, quantity_units: 1, unit_price_cents: 10_000 }] } },
      'SellerAR'
    );

    const d = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(d.status).toBe('PROPOSED');

    const drafts = asArray(await listCreditMemos(workspaceId, { customer_id: customerId, status: 'DRAFT' }, 'SellerAdmin'));
    expect(drafts.length).toBeGreaterThan(0);
  });

  test('DSP_014: accept_resolution issues+applies proposal credit and closes dispute', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoiceNoPO({ workspaceId, customerId, contractId, totalCents: 50_000, units: 5, unitPriceCents: 10_000 });
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);
    const dispute = await createDispute(workspaceId, invoiceId, { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_amount_cents: 10_000 }] }, 'BuyerAP');
    const disputeId = getDisputeId(dispute);

    await proposeResolution(
      workspaceId,
      disputeId,
      { proposed_credit: { items: [{ invoice_line_id: invoiceLineId, quantity_units: 1, unit_price_cents: 10_000 }] } },
      'SellerAR'
    );

    const before = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(before.amount_due_cents).toBe(50_000);
    expect(before.amount_disputed_cents).toBe(10_000);

    const res = await acceptResolution(workspaceId, disputeId, 'BuyerAP');
    expectSuccess(res);

    const d = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(d.status).toBe('CLOSED');

    const after = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(after.amount_due_cents).toBe(40_000);
    expect(after.amount_disputed_cents).toBe(0);
  });

  test('DSP_015: reject_resolution moves dispute to ESCALATED', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoiceNoPO({ workspaceId, customerId, contractId, totalCents: 50_000, units: 5, unitPriceCents: 10_000 });
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);
    const dispute = await createDispute(workspaceId, invoiceId, { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_amount_cents: 10_000 }] }, 'BuyerAP');
    const disputeId = getDisputeId(dispute);
    await proposeResolution(
      workspaceId,
      disputeId,
      { proposed_credit: { items: [{ invoice_line_id: invoiceLineId, quantity_units: 1, unit_price_cents: 10_000 }] } },
      'SellerAR'
    );

    const res = await rejectResolution(workspaceId, disputeId, 'BuyerAP');
    expectSuccess(res);
    const d = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(d.status).toBe('ESCALATED');
  });

  test('DSP_016: PROPOSED disputes auto-withdraw after three advances; draft credit memo is voided', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoiceNoPO({ workspaceId, customerId, contractId, totalCents: 50_000, units: 5, unitPriceCents: 10_000 });
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);
    const dispute = await createDispute(workspaceId, invoiceId, { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_amount_cents: 10_000 }] }, 'BuyerAP');
    const disputeId = getDisputeId(dispute);
    await proposeResolution(
      workspaceId,
      disputeId,
      { proposed_credit: { items: [{ invoice_line_id: invoiceLineId, quantity_units: 1, unit_price_cents: 10_000 }] } },
      'SellerAR'
    );

    const draftList = asArray(await listCreditMemos(workspaceId, { customer_id: customerId, status: 'DRAFT' }, 'SellerAdmin'));
    expect(draftList.length).toBeGreaterThan(0);
    const draftId = getCreditMemoId(draftList[0]);

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const d = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(d.status).toBe('WITHDRAWN');

    const cm = await getCreditMemo(workspaceId, draftId, 'SellerAdmin');
    expect(cm.status).toBe('VOIDED');
  });

  test('DSP_017: disputed_units disputes that fraction of line total', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoiceNoPO({ workspaceId, customerId, contractId, totalCents: 100_000, units: 10, unitPriceCents: 10_000 });
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);

    await createDispute(workspaceId, invoiceId, { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_units: 2 }] }, 'BuyerAP');

    const after = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(after.amount_disputed_cents).toBe(20_000);
  });

  test('DSP_018: disputed_units + disputed_amount_cents mismatch fails ERR_INVALID_REQUEST', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoiceNoPO({ workspaceId, customerId, contractId, totalCents: 100_000, units: 10, unitPriceCents: 10_000 });
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/disputes`,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_units: 2, disputed_amount_cents: 30_000 }] },
      'BuyerAP'
    );
    await expectErrorCode(res, 'ERR_INVALID_REQUEST');
  });

  test('DSP_019: applying line-tied credit reduces amount_disputed_cents when it resolves disputed amounts', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoiceNoPO({ workspaceId, customerId, contractId, totalCents: 10_000, units: 1, unitPriceCents: 10_000 });
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);

    await createDispute(workspaceId, invoiceId, { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_amount_cents: 5_000 }] }, 'BuyerAP');
    const before = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(before.amount_disputed_cents).toBe(5_000);

    const cm = await createCreditMemo(
      workspaceId,
      customerId,
      { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: invoiceLineId, quantity_units: 1, unit_price_cents: 5_000 }] },
      'SellerAR'
    );
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAR');
    await applyCreditMemo(workspaceId, cmId, invoiceId, 'SellerAR');

    const after = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(after.amount_disputed_cents).toBe(0);
    expect(after.amount_due_cents).toBe(5_000);
  });

  test('DSP_020: cannot dispute amounts already paid (ERR_DISPUTE_AMOUNT_EXCEEDS_AVAILABLE)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoiceNoPO({ workspaceId, customerId, contractId, totalCents: 10_000, units: 1, unitPriceCents: 10_000 });

    const payment = await createPayment(workspaceId, customerId, { amount_cents: 7_000, allocations: [{ invoice_id: invoiceId, amount_cents: 7_000 }] }, 'BuyerAP');
    await markPaymentCleared(workspaceId, getPaymentId(payment), 'SellerAR');

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);
    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/disputes`,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_amount_cents: 9_000 }] },
      'BuyerAP'
    );
    await expectErrorCode(res, 'ERR_DISPUTE_AMOUNT_EXCEEDS_AVAILABLE');
  });

  test('DSP_021: cannot dispute invoice after write_off closed it (ERR_INVOICE_NOT_DISPUTABLE)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1 });
    const invoiceId = await createAcceptedInvoiceNoPO({ workspaceId, customerId, contractId, totalCents: 5_000, units: 1, unitPriceCents: 5_000 });

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const duePeriod = inv0.due_period_index as number;
    await advanceToPeriod(workspaceId, duePeriod + 3);

    const invCollections = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invCollections.collections_stage).toBe('COLLECTIONS');

    const wr = await writeOffInvoice(workspaceId, invoiceId, 'SellerAR');
    expectSuccess(wr);

    const invClosed = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invClosed.status).toBe('CLOSED');

    const invoiceLineId = getFirstInvoiceLineId(invClosed);
    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/disputes`,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_units: 1 }] },
      'BuyerAP'
    );
    await expectErrorCode(res, 'ERR_INVOICE_NOT_DISPUTABLE');
  });

  test('DSP_022: fraud dispute freezes customer, blocking buyer payments (ERR_CUSTOMER_FROZEN)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoiceNoPO({ workspaceId, customerId, contractId, totalCents: 10_000, units: 1, unitPriceCents: 10_000 });
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);

    await createDispute(workspaceId, invoiceId, { reason: 'FRAUD', items: [{ invoice_line_id: invoiceLineId, disputed_units: 1 }] }, 'BuyerAP');
    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('FROZEN');

    const res = await postAs(`/workspaces/${workspaceId}/customers/${customerId}/payments`, { amount_cents: 1000 }, 'BuyerAP');
    await expectErrorCode(res, 'ERR_CUSTOMER_FROZEN');
  });

  test('DSP_023: accept fails if dispute covers only part of non-matchable portion (ERR_MATCH_EXCEPTION)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: true });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { po_number: `PO-${uniqueId('po')}`, lines: [{ ordered_units: 10, unit_price_cents: 10_000, is_service: false }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    await recordReceipt(workspaceId, poId, [{ purchase_order_line_id: poLineId, received_units: 0 }], 'BuyerAP').then(expectSuccess);

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { description: 'Goods', quantity_units: 10, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('SENT');
    expect(inv.match_status).toBe('EXCEPTION');
    const invoiceLineId = getFirstInvoiceLineId(inv);

    await createDispute(workspaceId, invoiceId, { reason: 'MISSING_RECEIPT', items: [{ invoice_line_id: invoiceLineId, disputed_units: 5 }] }, 'BuyerAP');

    const res = await acceptInvoice(workspaceId, invoiceId, 'BuyerAP');
    await expectErrorCode(res, 'ERR_MATCH_EXCEPTION');
  });

  test('DSP_024: line-tied credit applied to disputed line reduces amount_disputed_cents by credited amount', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoiceNoPO({ workspaceId, customerId, contractId, totalCents: 50_000, units: 5, unitPriceCents: 10_000 });

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv0);

    await createDispute(workspaceId, invoiceId, { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_amount_cents: 10_000 }] }, 'BuyerAP');
    const before = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(before.amount_disputed_cents).toBe(10_000);
    expect(before.amount_due_cents).toBe(50_000);

    const cm = await createCreditMemo(
      workspaceId,
      customerId,
      { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: invoiceLineId, quantity_units: 1, unit_price_cents: 3_000 }] },
      'SellerAR'
    );
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAR');
    await applyCreditMemo(workspaceId, cmId, invoiceId, 'SellerAR');

    const after = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(after.amount_disputed_cents).toBe(7_000);
    expect(after.amount_due_cents).toBe(47_000);
  });

  test('DSP_025: propose_resolution forbidden for BuyerAP (ERR_FORBIDDEN_FOR_ROLE)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoiceNoPO({ workspaceId, customerId, contractId, totalCents: 10_000, units: 1, unitPriceCents: 10_000 });
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);
    const dispute = await createDispute(workspaceId, invoiceId, { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_amount_cents: 1000 }] }, 'BuyerAP');
    const disputeId = getDisputeId(dispute);

    const res = await postAs(`/workspaces/${workspaceId}/disputes/${disputeId}/propose_resolution`, { proposed_credit: { items: [] } }, 'BuyerAP');
    await expectErrorCode(res, 'ERR_FORBIDDEN_FOR_ROLE');
  });

  test('DSP_026: seller_respond forbidden for BuyerAP (ERR_FORBIDDEN_FOR_ROLE)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoiceNoPO({ workspaceId, customerId, contractId, totalCents: 10_000, units: 1, unitPriceCents: 10_000 });
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);
    const dispute = await createDispute(workspaceId, invoiceId, { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_amount_cents: 1000 }] }, 'BuyerAP');
    const disputeId = getDisputeId(dispute);

    const res = await postAs(`/workspaces/${workspaceId}/disputes/${disputeId}/seller_respond`, {}, 'BuyerAP');
    await expectErrorCode(res, 'ERR_FORBIDDEN_FOR_ROLE');
  });

  test('DSP_027: cannot open a second dispute even if second is FRAUD (ERR_DISPUTE_ALREADY_ACTIVE)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoiceNoPO({ workspaceId, customerId, contractId, totalCents: 10_000, units: 1, unitPriceCents: 10_000 });
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);
    await createDispute(workspaceId, invoiceId, { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_amount_cents: 1000 }] }, 'BuyerAP');

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/disputes`,
      { reason: 'FRAUD', items: [{ invoice_line_id: invoiceLineId, disputed_units: 1 }] },
      'BuyerAP'
    );
    await expectErrorCode(res, 'ERR_DISPUTE_ALREADY_ACTIVE');
  });

  test('DSP_028: seller_respond on ESCALATED dispute succeeds but remains ESCALATED', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoiceNoPO({ workspaceId, customerId, contractId, totalCents: 10_000, units: 1, unitPriceCents: 10_000 });
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);
    const dispute = await createDispute(workspaceId, invoiceId, { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_amount_cents: 1000 }] }, 'BuyerAP');
    const disputeId = getDisputeId(dispute);

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');
    const d0 = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(d0.status).toBe('ESCALATED');

    const res = await sellerRespond(workspaceId, disputeId, 'SellerAR');
    expect(res.status).toBe('ESCALATED');
  });

  test('DSP_029: paying full invoice except disputed portion leaves amount_due == amount_disputed and invoice not closed', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoiceNoPO({ workspaceId, customerId, contractId, totalCents: 10_000, units: 1, unitPriceCents: 10_000 });

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv0);
    await createDispute(workspaceId, invoiceId, { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_amount_cents: 3000 }] }, 'BuyerAP');

    const payment = await createPayment(workspaceId, customerId, { amount_cents: 7000, allocations: [{ invoice_id: invoiceId, amount_cents: 7000 }] }, 'BuyerAP');
    await markPaymentCleared(workspaceId, getPaymentId(payment), 'SellerAR');

    const inv1 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv1.amount_due_cents).toBe(inv1.amount_disputed_cents);
    expect(inv1.amount_due_cents).toBe(3000);
    expect(inv1.status).not.toBe('CLOSED');
  });

  test('DSP_030: fully disputed invoices remain collections_stage CURRENT even after many advances', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1 });
    const invoiceId = await createAcceptedInvoiceNoPO({ workspaceId, customerId, contractId, totalCents: 10_000, units: 1, unitPriceCents: 10_000 });

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv0);
    await createDispute(workspaceId, invoiceId, { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_amount_cents: 10_000 }] }, 'BuyerAP');

    for (let i = 0; i < 6; i++) await advancePeriod(workspaceId, 'System');

    const inv1 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv1.amount_disputed_cents).toBe(inv1.amount_due_cents);
    expect(inv1.collections_stage).toBe('CURRENT');
  });

  test('DEEP_012: proposed dispute auto-withdraw releases disputed amount and triggers finance charge + collections stage update', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1 });

    const invoiceId = await createAcceptedInvoiceNoPO({ workspaceId, customerId, contractId, totalCents: 100_000, units: 10, unitPriceCents: 10_000 });

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv0);
    const dispute = await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_amount_cents: 100_000 }] },
      'BuyerAP'
    );
    const disputeId = getDisputeId(dispute);
    await proposeResolution(
      workspaceId,
      disputeId,
      { proposed_credit: { items: [{ invoice_line_id: invoiceLineId, quantity_units: 10, unit_price_cents: 10_000 }] } },
      'SellerAR'
    );

    const drafts = asArray(await listCreditMemos(workspaceId, { customer_id: customerId, status: 'DRAFT' }, 'SellerAdmin'));
    expect(drafts.length).toBeGreaterThan(0);
    const draftId = getCreditMemoId(drafts[0]);

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const before = await getCustomer(workspaceId, customerId, 'SellerAdmin');

    const out = await advancePeriod(workspaceId, 'System');
    const financeIds = (out as any).finance_charge_invoice_ids as string[] | undefined;
    expect(Array.isArray(financeIds)).toBe(true);
    expect(financeIds?.length).toBe(1);

    const d = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(d.status).toBe('WITHDRAWN');

    const cm = await getCreditMemo(workspaceId, draftId, 'SellerAdmin');
    expect(cm.status).toBe('VOIDED');

    const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter.amount_disputed_cents).toBe(0);
    expect(invAfter.collections_stage).toBe('FINAL_NOTICE');

    const finance = await getInvoice(workspaceId, financeIds![0], 'SellerAdmin');
    expect(finance.type).toBe('FINANCE_CHARGE');
    expect(finance.status).toBe('ACCEPTED');
    expect(finance.invoice_total_cents).toBe(2_500);
    expect(finance.amount_due_cents).toBe(2_500);

    const after = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(after.balance_due_cents).toBe(before.balance_due_cents + 2_500);
  });
});
