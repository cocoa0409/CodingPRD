import { postAs } from '../../../test-helpers/api-client';
import { expectErrorCode, expectSuccess } from '../../../test-helpers/assertions';
import { setupWorkspaceCustomerContract } from '../../../test-helpers/fixtures';
import {
  acceptInvoice,
  acceptResolution,
  addInvoiceLine,
  advancePeriod,
  applyCreditMemo,
  closeBooks,
  closeCustomer,
  createCreditMemo,
  createDispute,
  createInvoice,
  createPayment,
  createPurchaseOrder,
  finalizeInvoice,
  getCreditMemo,
  getCreditMemoId,
  getCustomer,
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
  voidCreditMemo,
  uniqueId
} from '../../../test-helpers/resources';

describe('Credit Memo and Adjustment Tests', () => {
  async function createAcceptedInvoice(params: {
    workspaceId: string;
    customerId: string;
    contractId: string;
    totalCents: number;
    quantityUnits: number;
    unitPriceCents: number;
  }) {
    const invoice = await createInvoice(params.workspaceId, params.customerId, { contract_id: params.contractId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(params.workspaceId, invoiceId, { quantity_units: params.quantityUnits, unit_price_cents: params.unitPriceCents }, 'SellerAR');
    await finalizeInvoice(params.workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${params.workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(params.workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv = await getInvoice(params.workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('ACCEPTED');
    expect(inv.amount_due_cents).toBe(params.totalCents);
    return invoiceId;
  }

  async function createPoBackedAcceptedInvoice(params: {
    workspaceId: string;
    customerId: string;
    contractId: string;
    orderedUnits: number;
    invoiceUnits: number;
    unitPriceCents: number;
    isService: boolean;
    recordReceiptUnits?: number;
  }) {
    const po = await createPurchaseOrder(
      params.workspaceId,
      params.customerId,
      { po_number: `PO-${uniqueId('po')}`, lines: [{ ordered_units: params.orderedUnits, unit_price_cents: params.unitPriceCents, is_service: params.isService }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(params.workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    if (!params.isService) {
      await postAs(
        `/workspaces/${params.workspaceId}/purchase_orders/${poId}/record_receipt`,
        { items: [{ purchase_order_line_id: poLineId, received_units: params.recordReceiptUnits ?? 0 }] },
        'BuyerAP'
      ).then(expectSuccess);
    }

    const invoice = await createInvoice(
      params.workspaceId,
      params.customerId,
      { contract_id: params.contractId, purchase_order_id: poId, external_invoice_ref: `INV-${uniqueId('ext')}` },
      'SellerAR'
    );
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(
      params.workspaceId,
      invoiceId,
      { quantity_units: params.invoiceUnits, unit_price_cents: params.unitPriceCents, purchase_order_line_id: poLineId },
      'SellerAR'
    );
    await finalizeInvoice(params.workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${params.workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(params.workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);
    return { invoiceId, poId };
  }

  test('CM_001: issuing credit memo increases available credit; invoice due unchanged until apply', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, totalCents: 20_000, quantityUnits: 2, unitPriceCents: 10_000 });

    const cust0 = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.amount_due_cents).toBe(20_000);

    const creditMemo = await createCreditMemo(
      workspaceId,
      customerId,
      {
        invoice_id: invoiceId,
        reason: 'GOODWILL',
        items: [{ invoice_line_id: getFirstInvoiceLineId(inv0), quantity_units: 1, unit_price_cents: 5000 }]
      },
      'SellerAR'
    );
    const cmId = getCreditMemoId(creditMemo);

    await issueCreditMemo(workspaceId, cmId, 'SellerAR');

    const cust1 = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust1.available_credit_cents).toBe(cust0.available_credit_cents + 5000);

    const inv1 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv1.amount_due_cents).toBe(20_000);
  });

  test('CM_002: applying credit memo reduces invoice amount_due', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, totalCents: 20_000, quantityUnits: 2, unitPriceCents: 10_000 });
    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');

    const cm = await createCreditMemo(
      workspaceId,
      customerId,
      { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: getFirstInvoiceLineId(inv0), quantity_units: 1, unit_price_cents: 5000 }] },
      'SellerAR'
    );
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAR');

    await applyCreditMemo(workspaceId, cmId, invoiceId, 'SellerAR');

    const inv1 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv1.amount_due_cents).toBe(15_000);
  });

  test('CM_003: applying oversized credit closes invoice and leaves remainder as available credit', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, totalCents: 20_000, quantityUnits: 2, unitPriceCents: 10_000 });
    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');

    const cm = await createCreditMemo(
      workspaceId,
      customerId,
      { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: getFirstInvoiceLineId(inv0), quantity_units: 6, unit_price_cents: 5000 }] },
      'SellerAR'
    );
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAR');

    await applyCreditMemo(workspaceId, cmId, invoiceId, 'SellerAR');

    const inv1 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv1.amount_due_cents).toBe(0);
    expect(inv1.status).toBe('CLOSED');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.available_credit_cents).toBe(10_000);
  });

  test('CM_004: SellerAR cannot issue goodwill credit > $1000 (ERR_CREDIT_EXCEEDS_AUTHORITY)', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomerContract();

    const cm = await createCreditMemo(
      workspaceId,
      customerId,
      { reason: 'GOODWILL', items: [{ quantity_units: 15, unit_price_cents: 10_000 }] },
      'SellerAR'
    );
    const cmId = getCreditMemoId(cm);

    const res = await postAs(`/workspaces/${workspaceId}/credit_memos/${cmId}/issue`, {}, 'SellerAR');
    await expectErrorCode(res, 'ERR_CREDIT_EXCEEDS_AUTHORITY');
  });

  test('CM_005: SellerAdmin can issue goodwill credit > $1000', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomerContract();
    const cm = await createCreditMemo(
      workspaceId,
      customerId,
      { reason: 'GOODWILL', items: [{ quantity_units: 15, unit_price_cents: 10_000 }] },
      'SellerAdmin'
    );
    const cmId = getCreditMemoId(cm);
    const res = await postAs(`/workspaces/${workspaceId}/credit_memos/${cmId}/issue`, {}, 'SellerAdmin');
    expectSuccess(res);
  });

  test('CM_006: SellerAR total goodwill per period cap enforced at $2500/customer/period', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomerContract();

    const cm1 = await createCreditMemo(workspaceId, customerId, { reason: 'GOODWILL', items: [{ quantity_units: 10, unit_price_cents: 10_000 }] }, 'SellerAR');
    const cm2 = await createCreditMemo(workspaceId, customerId, { reason: 'GOODWILL', items: [{ quantity_units: 10, unit_price_cents: 10_000 }] }, 'SellerAR');
    const cm3 = await createCreditMemo(workspaceId, customerId, { reason: 'GOODWILL', items: [{ quantity_units: 5, unit_price_cents: 10_000 }] }, 'SellerAR');

    await issueCreditMemo(workspaceId, getCreditMemoId(cm1), 'SellerAR');
    await issueCreditMemo(workspaceId, getCreditMemoId(cm2), 'SellerAR');
    await issueCreditMemo(workspaceId, getCreditMemoId(cm3), 'SellerAR');

    const cmNext = await createCreditMemo(workspaceId, customerId, { reason: 'GOODWILL', items: [{ quantity_units: 1, unit_price_cents: 10_000 }] }, 'SellerAR');
    const nextId = getCreditMemoId(cmNext);
    const res = await postAs(`/workspaces/${workspaceId}/credit_memos/${nextId}/issue`, {}, 'SellerAR');
    await expectErrorCode(res, 'ERR_CREDIT_EXCEEDS_AUTHORITY');
  });

  test('CM_007: SellerAdmin can exceed per-customer-per-period goodwill cap', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomerContract();

    const cm1 = await createCreditMemo(workspaceId, customerId, { reason: 'GOODWILL', items: [{ quantity_units: 10, unit_price_cents: 10_000 }] }, 'SellerAR');
    const cm2 = await createCreditMemo(workspaceId, customerId, { reason: 'GOODWILL', items: [{ quantity_units: 10, unit_price_cents: 10_000 }] }, 'SellerAR');
    const cm3 = await createCreditMemo(workspaceId, customerId, { reason: 'GOODWILL', items: [{ quantity_units: 5, unit_price_cents: 10_000 }] }, 'SellerAR');

    await issueCreditMemo(workspaceId, getCreditMemoId(cm1), 'SellerAR');
    await issueCreditMemo(workspaceId, getCreditMemoId(cm2), 'SellerAR');
    await issueCreditMemo(workspaceId, getCreditMemoId(cm3), 'SellerAR');

    const cmNext = await createCreditMemo(workspaceId, customerId, { reason: 'GOODWILL', items: [{ quantity_units: 1, unit_price_cents: 10_000 }] }, 'SellerAdmin');
    const nextId = getCreditMemoId(cmNext);
    const res = await postAs(`/workspaces/${workspaceId}/credit_memos/${nextId}/issue`, {}, 'SellerAdmin');
    expectSuccess(res);
  });

  test('CM_008: dispute-proposal draft credit memo cannot be issued manually (ERR_INVALID_STATE_TRANSITION)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, totalCents: 50_000, quantityUnits: 5, unitPriceCents: 10_000 });
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);

    const dispute = await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_amount_cents: 10_000 }] },
      'BuyerAP'
    );
    const disputeId = getDisputeId(dispute);

    await proposeResolution(
      workspaceId,
      disputeId,
      { proposed_credit: { items: [{ invoice_line_id: invoiceLineId, quantity_units: 1, unit_price_cents: 10_000 }] } },
      'SellerAR'
    );

    const drafts = await listCreditMemos(workspaceId, { customer_id: customerId, status: 'DRAFT' }, 'SellerAdmin');
    expect(drafts.length).toBe(1);
    const cmId = getCreditMemoId(drafts[0]);

    const res = await postAs(`/workspaces/${workspaceId}/credit_memos/${cmId}/issue`, {}, 'SellerAR');
    await expectErrorCode(res, 'ERR_INVALID_STATE_TRANSITION');
  });

  test('CM_009: voiding an issued-but-unapplied credit memo succeeds and reduces available credit', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, totalCents: 20_000, quantityUnits: 2, unitPriceCents: 10_000 });
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');

    const cust0 = await getCustomer(workspaceId, customerId, 'SellerAdmin');

    const cm = await createCreditMemo(
      workspaceId,
      customerId,
      { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: getFirstInvoiceLineId(inv), quantity_units: 1, unit_price_cents: 5000 }] },
      'SellerAR'
    );
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAR');

    const cust1 = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust1.available_credit_cents).toBe(cust0.available_credit_cents + 5000);

    const res = await voidCreditMemo(workspaceId, cmId, 'SellerAR');
    expectSuccess(res);

    const cmGot = await getCreditMemo(workspaceId, cmId, 'SellerAdmin');
    expect(cmGot.status).toBe('VOIDED');

    const cust2 = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust2.available_credit_cents).toBe(cust0.available_credit_cents);
  });

  test('CM_010: applied credit memos cannot be voided (ERR_INVALID_STATE_TRANSITION)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, totalCents: 20_000, quantityUnits: 2, unitPriceCents: 10_000 });
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');

    const cm = await createCreditMemo(
      workspaceId,
      customerId,
      { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: getFirstInvoiceLineId(inv), quantity_units: 1, unit_price_cents: 5000 }] },
      'SellerAR'
    );
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAR');
    await applyCreditMemo(workspaceId, cmId, invoiceId, 'SellerAR');

    const res = await voidCreditMemo(workspaceId, cmId, 'SellerAR');
    await expectErrorCode(res, 'ERR_INVALID_STATE_TRANSITION');
  });

  test('CM_011: early pay discount credit memo is locked (ERR_CREDIT_MEMO_LOCKED)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, totalCents: 100_000, quantityUnits: 10, unitPriceCents: 10_000 });

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const due = inv0.amount_due_cents as number;
    expect(due).toBe(100_000);

    const payment = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 99_000, allocations: [{ invoice_id: invoiceId, amount_cents: 99_000 }] },
      'BuyerAP'
    );
    await markPaymentCleared(workspaceId, getPaymentId(payment), 'SellerAR');

    const inv1 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv1.status).toBe('CLOSED');
    expect(inv1.amount_due_cents).toBe(0);

    const cms = await listCreditMemos(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    expect(cms.length).toBe(1);
    const cmId = getCreditMemoId(cms[0]);

    const res = await voidCreditMemo(workspaceId, cmId, 'SellerAdmin');
    await expectErrorCode(res, 'ERR_CREDIT_MEMO_LOCKED');
  });

  test('CM_012: line-tied unit credits reduce PO net_billed_units', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: true });

    const { invoiceId, poId } = await createPoBackedAcceptedInvoice({
      workspaceId,
      customerId,
      contractId,
      orderedUnits: 10,
      invoiceUnits: 10,
      unitPriceCents: 10_000,
      isService: true
    });
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);

    const cm = await createCreditMemo(
      workspaceId,
      customerId,
      { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: invoiceLineId, quantity_units: 2, unit_price_cents: 10_000 }] },
      'SellerAR'
    );
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAR');
    await applyCreditMemo(workspaceId, cmId, invoiceId, 'SellerAR');

    const po = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    expect(po.lines[0].net_billed_units).toBe(8);
  });

  test('CM_013: line-tied credit applied to disputed line reduces amount_due and amount_disputed', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, totalCents: 20_000, quantityUnits: 2, unitPriceCents: 10_000 });
    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv0);

    await createDispute(workspaceId, invoiceId, { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_amount_cents: 5000 }] }, 'BuyerAP');

    const cm = await createCreditMemo(
      workspaceId,
      customerId,
      { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: invoiceLineId, quantity_units: 3, unit_price_cents: 1000 }] },
      'SellerAR'
    );
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAR');
    await applyCreditMemo(workspaceId, cmId, invoiceId, 'SellerAR');

    const inv1 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv1.amount_due_cents).toBe(17_000);
    expect(inv1.amount_disputed_cents).toBe(2000);
  });

  test('CM_014: customer-level credit memo can be applied to invoice', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, totalCents: 20_000, quantityUnits: 2, unitPriceCents: 10_000 });

    const cust0 = await getCustomer(workspaceId, customerId, 'SellerAdmin');

    const cm = await createCreditMemo(
      workspaceId,
      customerId,
      { reason: 'GOODWILL', items: [{ quantity_units: 1, unit_price_cents: 5000 }] },
      'SellerAR'
    );
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAR');

    const cust1 = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust1.available_credit_cents).toBe(cust0.available_credit_cents + 5000);

    await applyCreditMemo(workspaceId, cmId, invoiceId, 'SellerAR');

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.amount_due_cents).toBe(15_000);
    const cust2 = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust2.available_credit_cents).toBe(cust0.available_credit_cents);
  });

  test('CM_015: cannot apply credit memo to CLOSED invoice (ERR_INVOICE_NOT_CREDITABLE)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, totalCents: 20_000, quantityUnits: 2, unitPriceCents: 10_000 });

    const payment = await createPayment(workspaceId, customerId, { amount_cents: 20_000, allocations: [{ invoice_id: invoiceId, amount_cents: 20_000 }] }, 'BuyerAP');
    await markPaymentCleared(workspaceId, getPaymentId(payment), 'SellerAR');
    const invClosed = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invClosed.status).toBe('CLOSED');

    const cm = await createCreditMemo(workspaceId, customerId, { reason: 'GOODWILL', items: [{ quantity_units: 1, unit_price_cents: 5000 }] }, 'SellerAR');
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAR');

    const res = await postAs(`/workspaces/${workspaceId}/credit_memos/${cmId}/apply`, { invoice_id: invoiceId }, 'SellerAR');
    await expectErrorCode(res, 'ERR_INVOICE_NOT_CREDITABLE');
  });

  test('CM_016: credit memo item invoice_line_id must belong to invoice_id (ERR_INVALID_REQUEST)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const i1 = await createAcceptedInvoice({ workspaceId, customerId, contractId, totalCents: 10_000, quantityUnits: 1, unitPriceCents: 10_000 });
    const i2 = await createAcceptedInvoice({ workspaceId, customerId, contractId, totalCents: 10_000, quantityUnits: 1, unitPriceCents: 10_000 });

    const inv2 = await getInvoice(workspaceId, i2, 'SellerAdmin');
    const badLineId = getFirstInvoiceLineId(inv2);

    const res = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/credit_memos`,
      {
        invoice_id: i1,
        reason: 'GOODWILL',
        items: [{ invoice_line_id: badLineId, quantity_units: 1, unit_price_cents: 5000 }]
      },
      'SellerAR'
    );
    await expectErrorCode(res, 'ERR_INVALID_REQUEST');
  });

  test('CM_017: applying credits can clear CREDIT_HOLD when exposure drops below $5k and no other blockers', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1 });
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, totalCents: 2_600_000, quantityUnits: 260, unitPriceCents: 10_000 });

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const duePeriod = inv0.due_period_index as number;

    while (true) {
      const ws = await getWorkspace(workspaceId, 'SellerAdmin');
      if (ws.period_index >= duePeriod + 1) break;
      await advancePeriod(workspaceId, 'System');
    }

    const custHold = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custHold.status).toBe('CREDIT_HOLD');

    const invoiceLineId = getFirstInvoiceLineId(await getInvoice(workspaceId, invoiceId, 'SellerAdmin'));

    const cm = await createCreditMemo(
      workspaceId,
      customerId,
      { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: invoiceLineId, quantity_units: 220, unit_price_cents: 10_000 }] },
      'SellerAdmin'
    );
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAdmin');
    await applyCreditMemo(workspaceId, cmId, invoiceId, 'SellerAdmin');

    const custActive = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custActive.status).toBe('ACTIVE');
  });

  test('CM_018: cannot open new disputes on invoice after credits close it (ERR_INVOICE_NOT_DISPUTABLE)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, totalCents: 10_000, quantityUnits: 1, unitPriceCents: 10_000 });
    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv0);

    const cm = await createCreditMemo(
      workspaceId,
      customerId,
      { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: invoiceLineId, quantity_units: 1, unit_price_cents: 10_000 }] },
      'SellerAR'
    );
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAR');
    await applyCreditMemo(workspaceId, cmId, invoiceId, 'SellerAR');

    const inv1 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv1.status).toBe('CLOSED');

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/disputes`,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_units: 1 }] },
      'BuyerAP'
    );
    await expectErrorCode(res, 'ERR_INVOICE_NOT_DISPUTABLE');
  });

  test('CM_019: dispute-tied credits do not count toward SellerAR goodwill caps', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, totalCents: 300_000, quantityUnits: 30, unitPriceCents: 10_000 });
    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv0);

    const dispute = await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_amount_cents: 200_000 }] },
      'BuyerAP'
    );
    const disputeId = getDisputeId(dispute);

    await proposeResolution(
      workspaceId,
      disputeId,
      { proposed_credit: { items: [{ invoice_line_id: invoiceLineId, quantity_units: 20, unit_price_cents: 10_000 }] } },
      'SellerAR'
    );
    await acceptResolution(workspaceId, disputeId, 'BuyerAP').then(expectSuccess);

    const gw = await createCreditMemo(
      workspaceId,
      customerId,
      { reason: 'GOODWILL', items: [{ quantity_units: 10, unit_price_cents: 10_000 }] },
      'SellerAR'
    );
    const gwId = getCreditMemoId(gw);
    const res = await postAs(`/workspaces/${workspaceId}/credit_memos/${gwId}/issue`, {}, 'SellerAR');
    expectSuccess(res);
  });

  test('CM_020: closing books for prior periods does not block issuing credit memo in current period', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomerContract();
    const cm = await createCreditMemo(workspaceId, customerId, { reason: 'GOODWILL', items: [{ quantity_units: 5, unit_price_cents: 10_000 }] }, 'SellerAR');
    const cmId = getCreditMemoId(cm);

    await advancePeriod(workspaceId, 'System');
    await closeBooks(workspaceId, 'Auditor').then(expectSuccess);

    const res = await postAs(`/workspaces/${workspaceId}/credit_memos/${cmId}/issue`, {}, 'SellerAR');
    expectSuccess(res);
  });

  test('CM_021: credits + overpayment -> unapplied cash remainder and no available credits', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();

    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, totalCents: 50_000, quantityUnits: 5, unitPriceCents: 10_000 });

    const cm = await createCreditMemo(workspaceId, customerId, { reason: 'GOODWILL', items: [{ quantity_units: 1, unit_price_cents: 10_000 }] }, 'SellerAR');
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAR');
    await applyCreditMemo(workspaceId, cmId, invoiceId, 'SellerAR');

    const payment = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 60_000, allocations: [{ invoice_id: invoiceId, amount_cents: 40_000 }] },
      'BuyerAP'
    );
    await markPaymentCleared(workspaceId, getPaymentId(payment), 'SellerAR');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.available_credit_cents).toBe(0);
    expect(cust.balance_due_cents).toBe(0);
    expect(cust.unapplied_cash_cents).toBe(20_000);
  });

  test('CM_022: cannot close customer while available credits remain (ERR_CUSTOMER_NOT_SETTLED)', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomerContract();
    const cm = await createCreditMemo(workspaceId, customerId, { reason: 'GOODWILL', items: [{ quantity_units: 1, unit_price_cents: 10_000 }] }, 'SellerAR');
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAR');

    const res = await closeCustomer(workspaceId, customerId, 'SellerAdmin');
    await expectErrorCode(res, 'ERR_CUSTOMER_NOT_SETTLED');
  });
});
