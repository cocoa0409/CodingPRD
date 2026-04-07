import { postAs } from '../../../test-helpers/api-client';
import { expectErrorCode, expectSuccess } from '../../../test-helpers/assertions';
import { createSentMatchedInvoice, setupWorkspaceCustomerContract } from '../../../test-helpers/fixtures';
import {
  acceptInvoice,
  addInvoiceLine,
  advancePeriod,
  applyCreditMemo,
  cancelPurchaseOrder,
  closeBooks,
  createCustomer,
  createCreditMemo,
  createDispute,
  createInvoice,
  createPayment,
  createPurchaseOrder,
  createWorkspace,
  finalizeInvoice,
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
  getPayment,
  getWorkspace,
  getPaymentId,
  getPurchaseOrder,
  getPurchaseOrderId,
  issueCreditMemo,
  listInvoices,
  markPaymentCleared,
  reversePayment,
  sellerRespond,
  voidInvoice,
  uniqueId
} from '../../../test-helpers/resources';

describe('Invoice Lifecycle Tests', () => {
  async function createMatchedSentInvoice(params: any) {
    return createSentMatchedInvoice({ ...params, receiptUnits: params.recordReceiptUnits });
  }

  test('INV_001: create invoice yields DRAFT with invoice_total_cents 0', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();

    const invoice = await createInvoice(
      workspaceId,
      customerId,
      { contract_id: contractId, external_invoice_ref: `REF-${uniqueId('ref')}` },
      'SellerAR'
    );
    expect(invoice.status).toBe('DRAFT');
    expect(invoice.invoice_total_cents).toBe(0);
  });

  test('INV_002: adding lines keeps invoice_total_cents 0 until finalize; line visible via GET', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);

    await addInvoiceLine(workspaceId, invoiceId, { description: 'Widgets', quantity_units: 2, unit_price_cents: 10_000 }, 'SellerAR');

    const got = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(got.status).toBe('DRAFT');
    expect(got.invoice_total_cents).toBe(0);
    expect(Array.isArray(got.lines)).toBe(true);
    expect(got.lines.length).toBe(1);
    expect(got.lines[0].quantity_units).toBe(2);
    expect(got.lines[0].unit_price_cents).toBe(10_000);
  });

  test('INV_003: finalize sets status FINALIZED and issued_period_index = workspace period_index', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 2, unit_price_cents: 10_000 }, 'SellerAR');

    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');

    const got = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(got.status).toBe('FINALIZED');
    expect(got.issued_period_index).toBe(0);
    expect(got.invoice_total_cents).toBe(20_000);
    expect(got.amount_due_cents).toBe(20_000);
    expect(got.amount_disputed_cents).toBe(0);
    expect(got.match_status).toBe('NOT_APPLICABLE');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(20_000);
  });

  test('INV_004: cannot add line to FINALIZED invoice (ERR_INVALID_STATE_TRANSITION)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 2, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/lines`,
      { description: 'More', quantity_units: 1, unit_price_cents: 1000 },
      'SellerAR'
    );
    await expectErrorCode(res, 'ERR_INVALID_STATE_TRANSITION');
  });

  test('INV_005: send moves FINALIZED -> SENT and sets delivered_period_index', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 2, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');

    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);

    const got = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(got.status).toBe('SENT');
    expect(got.delivered_period_index).toBe(0);
  });

  test('INV_006: cannot send DRAFT invoice (ERR_INVALID_STATE_TRANSITION)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);

    const res = await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR');
    await expectErrorCode(res, 'ERR_INVALID_STATE_TRANSITION');

    const got = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(got.status).toBe('DRAFT');
    expect(got.delivered_period_index == null).toBe(true);
    expect(got.accepted_period_index == null).toBe(true);
    expect(got.due_period_index == null).toBe(true);
  });

  test('INV_007: accept SENT+MATCHED invoice succeeds and sets accepted_period_index', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: false });
    const { invoiceId } = await createMatchedSentInvoice({ workspaceId, customerId, contractId, orderedUnits: 10, invoiceUnits: 10, isService: true });

    const before = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(before.status).toBe('SENT');
    expect(before.match_status).toBe('MATCHED');

    const res = await acceptInvoice(workspaceId, invoiceId, 'BuyerAP');
    expectSuccess(res);
    const after = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(after.status).toBe('ACCEPTED');
    expect(after.accepted_period_index).toBe(0);
  });

  test('INV_008: accept fails on match_status EXCEPTION (ERR_MATCH_EXCEPTION)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: false });
    const { invoiceId } = await createMatchedSentInvoice({
      workspaceId,
      customerId,
      contractId,
      orderedUnits: 10,
      invoiceUnits: 12,
      isService: true
    });

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.match_status).toBe('EXCEPTION');

    const res = await acceptInvoice(workspaceId, invoiceId, 'BuyerAP');
    await expectErrorCode(res, 'ERR_MATCH_EXCEPTION');

    const after = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(after.status).toBe('SENT');
    expect(after.accepted_period_index == null).toBe(true);
    expect(after.due_period_index == null).toBe(true);
  });

  test('INV_009: acceptance sets due_period_index = accepted_period_index + payment_terms_periods', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });
    const { invoiceId } = await createMatchedSentInvoice({ workspaceId, customerId, contractId, orderedUnits: 10, invoiceUnits: 10, isService: true });

    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('ACCEPTED');
    expect(inv.due_period_index).toBe(inv.accepted_period_index + 2);
  });

  test('INV_010: requires_po contract finalize fails ERR_PO_REQUIRED when invoice has no purchase_order_id', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: true });
    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 2, unit_price_cents: 10_000 }, 'SellerAR');

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/finalize`,
      { override_hold: false, override_billing_cap: false, final_invoice: false },
      'SellerAR'
    );
    await expectErrorCode(res, 'ERR_PO_REQUIRED');

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('DRAFT');
    expect(inv.invoice_total_cents).toBe(0);
  });

  test('INV_011: finalize fails ERR_PO_NOT_OPEN when invoice references CANCELLED PO', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: true });
    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { po_number: `PO-${uniqueId('po')}`, lines: [{ ordered_units: 10, unit_price_cents: 10_000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    await cancelPurchaseOrder(workspaceId, poId, 'BuyerAP').then(expectSuccess);

    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const lineId = getFirstPurchaseOrderLineId(poFull);

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 10_000, purchase_order_line_id: lineId }, 'SellerAR');

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/finalize`,
      { override_hold: false, override_billing_cap: false, final_invoice: false },
      'SellerAR'
    );
    await expectErrorCode(res, 'ERR_PO_NOT_OPEN');

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('DRAFT');
    expect(inv.invoice_total_cents).toBe(0);

    const poAfter = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    expect(poAfter.status).toBe('CANCELLED');
  });

  test('INV_012: duplicate external_invoice_ref on finalized non-voided invoice fails ERR_DUPLICATE_EXTERNAL_REF', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();

    const inv1 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: 'REF1' }, 'SellerAR');
    const inv1Id = getInvoiceId(inv1);
    await addInvoiceLine(workspaceId, inv1Id, { quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, inv1Id, {}, 'SellerAR');

    const inv2 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: 'REF1' }, 'SellerAR');
    const inv2Id = getInvoiceId(inv2);
    await addInvoiceLine(workspaceId, inv2Id, { quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${inv2Id}/finalize`,
      { override_hold: false, override_billing_cap: false, final_invoice: false },
      'SellerAR'
    );
    await expectErrorCode(res, 'ERR_DUPLICATE_EXTERNAL_REF');

    const inv2After = await getInvoice(workspaceId, inv2Id, 'SellerAdmin');
    expect(inv2After.status).toBe('DRAFT');
    expect(inv2After.invoice_total_cents).toBe(0);

    const inv1After = await getInvoice(workspaceId, inv1Id, 'SellerAdmin');
    expect(inv1After.status).toBe('FINALIZED');
  });

  test('INV_013: duplicate external_invoice_ref is allowed after original invoice is VOIDED', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();

    const inv1 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: 'REF1' }, 'SellerAR');
    const inv1Id = getInvoiceId(inv1);
    await addInvoiceLine(workspaceId, inv1Id, { quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, inv1Id, {}, 'SellerAR');

    const voidRes = await voidInvoice(workspaceId, inv1Id, 'SellerAR');
    expectSuccess(voidRes);

    const inv2 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: 'REF1' }, 'SellerAR');
    const inv2Id = getInvoiceId(inv2);
    await addInvoiceLine(workspaceId, inv2Id, { quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${inv2Id}/finalize`,
      { override_hold: false, override_billing_cap: false, final_invoice: false },
      'SellerAR'
    );
    expectSuccess(res);
  });

  test('INV_014: can void a DRAFT invoice (status VOIDED)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');

    const res = await voidInvoice(workspaceId, invoiceId, 'SellerAR');
    expectSuccess(res);
    const got = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(got.status).toBe('VOIDED');
  });

  test('INV_015: can void FINALIZED-but-unsent invoice when no payments/disputes and books not closed', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');

    const res = await voidInvoice(workspaceId, invoiceId, 'SellerAR');
    expectSuccess(res);
    const got = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(got.status).toBe('VOIDED');
  });

  test('INV_016: cannot void SENT invoice (ERR_INVALID_STATE_TRANSITION)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const { invoiceId } = await createMatchedSentInvoice({ workspaceId, customerId, contractId, orderedUnits: 10, invoiceUnits: 10, isService: true });

    const res = await voidInvoice(workspaceId, invoiceId, 'SellerAR');
    await expectErrorCode(res, 'ERR_INVALID_STATE_TRANSITION');
  });

  test('INV_017: cannot void ACCEPTED invoice (ERR_INVALID_STATE_TRANSITION)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const { invoiceId } = await createMatchedSentInvoice({ workspaceId, customerId, contractId, orderedUnits: 10, invoiceUnits: 10, isService: true });
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const res = await voidInvoice(workspaceId, invoiceId, 'SellerAR');
    await expectErrorCode(res, 'ERR_INVALID_STATE_TRANSITION');
  });

  test('INV_018: cannot void invoice after books closed through its issued period (ERR_BOOKS_CLOSED)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');

    await advancePeriod(workspaceId, 'System');
    await closeBooks(workspaceId, 'Auditor').then(expectSuccess);

    const res = await voidInvoice(workspaceId, invoiceId, 'SellerAR');
    await expectErrorCode(res, 'ERR_BOOKS_CLOSED');
  });

  test('INV_019: SellerAdmin can void after books closed if there were never cleared payments', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');

    await advancePeriod(workspaceId, 'System');
    await closeBooks(workspaceId, 'Auditor').then(expectSuccess);

    const res = await voidInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expectSuccess(res);
    const got = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(got.status).toBe('VOIDED');
  });

  test('INV_020: void fails ERR_INVOICE_HAS_PAYMENTS when invoice has initiated allocated payment', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const { invoiceId } = await createMatchedSentInvoice({ workspaceId, customerId, contractId, orderedUnits: 10, invoiceUnits: 10, isService: true });
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const due = inv.amount_due_cents as number;

    await createPayment(
      workspaceId,
      customerId,
      { amount_cents: due, allocations: [{ invoice_id: invoiceId, amount_cents: due }] },
      'BuyerAP'
    );

    const res = await voidInvoice(workspaceId, invoiceId, 'SellerAdmin');
    await expectErrorCode(res, 'ERR_INVOICE_HAS_PAYMENTS');
  });

  test('INV_021: void fails ERR_INVOICE_HAS_DISPUTE when invoice has active dispute', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const { invoiceId } = await createMatchedSentInvoice({ workspaceId, customerId, contractId, orderedUnits: 10, invoiceUnits: 10, isService: true });

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);
    await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_units: 1 }] },
      'BuyerAP'
    );

    const res = await voidInvoice(workspaceId, invoiceId, 'SellerAdmin');
    await expectErrorCode(res, 'ERR_INVOICE_HAS_DISPUTE');
  });

  test('INV_022: cannot send a CLOSED invoice (ERR_INVALID_STATE_TRANSITION)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const { invoiceId } = await createMatchedSentInvoice({ workspaceId, customerId, contractId, orderedUnits: 10, invoiceUnits: 10, isService: true });
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const due = inv.amount_due_cents as number;
    const payment = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: due, allocations: [{ invoice_id: invoiceId, amount_cents: due }] },
      'BuyerAP'
    );
    await markPaymentCleared(workspaceId, getPaymentId(payment), 'SellerAR');

    const closed = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(closed.status).toBe('CLOSED');

    const res = await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR');
    await expectErrorCode(res, 'ERR_INVALID_STATE_TRANSITION');
  });

  test('INV_023: dispute before acceptance keeps amount_disputed_cents positive after acceptance', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const { invoiceId } = await createMatchedSentInvoice({ workspaceId, customerId, contractId, orderedUnits: 2, invoiceUnits: 2, isService: true, poUnitPriceCents: 10_000 });

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv0);

    await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_units: 1 }] },
      'BuyerAP'
    );

    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv1 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv1.status).toBe('ACCEPTED');
    expect(inv1.amount_disputed_cents).toBe(10_000);
  });

  test('INV_024: SERVICE_QUALITY dispute window closed beyond 2 periods after deemed acceptance', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });
    const { invoiceId } = await createMatchedSentInvoice({ workspaceId, customerId, contractId, orderedUnits: 10, invoiceUnits: 10, isService: true });

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const invAccepted = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAccepted.status).toBe('ACCEPTED');
    expect(invAccepted.accepted_period_index).toBe(1);

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const inv1 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv1);

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/disputes`,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_units: 1 }] },
      'BuyerAP'
    );
    await expectErrorCode(res, 'ERR_DISPUTE_WINDOW_CLOSED');
  });

  test('INV_025: TAX_ERROR disputes are allowed within six periods after acceptance', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 10 });
    const { invoiceId } = await createMatchedSentInvoice({ workspaceId, customerId, contractId, orderedUnits: 10, invoiceUnits: 10, isService: true });
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    for (let i = 0; i < 6; i++) await advancePeriod(workspaceId, 'System');

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/disputes`,
      { reason: 'TAX_ERROR', items: [{ invoice_line_id: invoiceLineId, disputed_amount_cents: 1000 }] },
      'BuyerAP'
    );
    expectSuccess(res);
  });

  test('INV_026: cannot dispute a CLOSED invoice (ERR_INVOICE_NOT_DISPUTABLE)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const { invoiceId } = await createMatchedSentInvoice({ workspaceId, customerId, contractId, orderedUnits: 10, invoiceUnits: 10, isService: true });
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const due = inv.amount_due_cents as number;
    const payment = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: due, allocations: [{ invoice_id: invoiceId, amount_cents: due }] },
      'BuyerAP'
    );
    await markPaymentCleared(workspaceId, getPaymentId(payment), 'SellerAR');

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const closed = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(closed.status).toBe('CLOSED');
    const invoiceLineId = getFirstInvoiceLineId(closed);

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/disputes`,
      { reason: 'DUPLICATE_INVOICE', items: [{ invoice_line_id: invoiceLineId, disputed_units: 1 }] },
      'BuyerAP'
    );
    await expectErrorCode(res, 'ERR_INVOICE_NOT_DISPUTABLE');
  });

  test('INV_028: FRAUD dispute in COLLECTIONS succeeds and freezes customer', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1 });
    const { invoiceId } = await createMatchedSentInvoice({ workspaceId, customerId, contractId, orderedUnits: 10, invoiceUnits: 10, isService: true });
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const duePeriod = inv0.due_period_index as number;
    while (true) {
      const w = await getWorkspace(workspaceId, 'SellerAdmin');
      if (w.period_index >= duePeriod + 3) break;
      await advancePeriod(workspaceId, 'System');
    }

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.collections_stage).toBe('COLLECTIONS');
    const invoiceLineId = getFirstInvoiceLineId(inv);

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/disputes`,
      { reason: 'FRAUD', items: [{ invoice_line_id: invoiceLineId, disputed_units: 1 }] },
      'BuyerAP'
    );
    expectSuccess(res);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('FROZEN');
  });

  test('INV_029: credit memo reducing amount_due to 0 closes invoice; collections_stage becomes CURRENT', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1 });
    const { invoiceId } = await createMatchedSentInvoice({ workspaceId, customerId, contractId, orderedUnits: 10, invoiceUnits: 10, isService: true });
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const duePeriod = inv0.due_period_index as number;

    while (true) {
      const w = await getWorkspace(workspaceId, 'SellerAdmin');
      if (w.period_index >= duePeriod + 3) break;
      await advancePeriod(workspaceId, 'System');
    }

    const invCollections = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invCollections.collections_stage).toBe('COLLECTIONS');
    const invoiceLineId = getFirstInvoiceLineId(invCollections);
    const amountDue = invCollections.amount_due_cents as number;

    const cm = await createCreditMemo(
      workspaceId,
      customerId,
      {
        invoice_id: invoiceId,
        reason: 'GOODWILL',
        items: [{ invoice_line_id: invoiceLineId, quantity_units: 10, unit_price_cents: 10_000 }]
      },
      'SellerAR'
    );
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAR');
    await applyCreditMemo(workspaceId, cmId, invoiceId, 'SellerAR');

    const invClosed = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invClosed.amount_due_cents).toBe(0);
    expect(invClosed.status).toBe('CLOSED');
    expect(invClosed.collections_stage).toBe('CURRENT');
    expect(amountDue).toBeGreaterThan(0);
  });

  test('INV_030: amount_disputed_cents updates while amount_due_cents stays unchanged', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const { invoiceId } = await createMatchedSentInvoice({ workspaceId, customerId, contractId, orderedUnits: 1, invoiceUnits: 1, isService: true, poUnitPriceCents: 10_000 });
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.amount_due_cents).toBe(10_000);
    const invoiceLineId = getFirstInvoiceLineId(inv0);

    await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_amount_cents: 3000 }] },
      'BuyerAP'
    );

    const inv1 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv1.amount_disputed_cents).toBe(3000);
    expect(inv1.amount_due_cents).toBe(10_000);
  });

  test('INV_034: external_invoice_ref uniqueness includes CLOSED invoices (not only active)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();

    const inv1 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: 'REF-1' }, 'SellerAR');
    const inv1Id = getInvoiceId(inv1);
    await addInvoiceLine(workspaceId, inv1Id, { quantity_units: 10, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, inv1Id, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${inv1Id}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, inv1Id, 'BuyerAP').then(expectSuccess);

    const due = (await getInvoice(workspaceId, inv1Id, 'SellerAdmin')).amount_due_cents as number;
    const payment = await createPayment(workspaceId, customerId, { amount_cents: due, allocations: [{ invoice_id: inv1Id, amount_cents: due }] }, 'BuyerAP');
    await markPaymentCleared(workspaceId, getPaymentId(payment), 'SellerAR');

    const closed = await getInvoice(workspaceId, inv1Id, 'SellerAdmin');
    expect(closed.status).toBe('CLOSED');

    const inv2 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: 'REF-1' }, 'SellerAR');
    const inv2Id = getInvoiceId(inv2);
    await addInvoiceLine(workspaceId, inv2Id, { quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${inv2Id}/finalize`,
      { override_hold: false, override_billing_cap: false, final_invoice: false },
      'SellerAR'
    );
    await expectErrorCode(res, 'ERR_DUPLICATE_EXTERNAL_REF');

    const stillDraft = await getInvoice(workspaceId, inv2Id, 'SellerAdmin');
    expect(stillDraft.status).toBe('DRAFT');
    expect(stillDraft.invoice_total_cents).toBe(0);
  });

  test('INV_035: finance charges respect $500 customer ceiling with proportional scaling + oldest-invoice leftover cents', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1, requires_po: false });

    async function createAndAcceptInvoice(totalCents: number, externalRef: string) {
      const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: externalRef }, 'SellerAR');
      const invoiceId = getInvoiceId(inv);
      await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 1, unit_price_cents: totalCents }, 'SellerAR');
      await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
      await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
      await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);
      return invoiceId;
    }

    await createAndAcceptInvoice(1_333_334, `INV-A-${uniqueId('inv035')}`);
    await advancePeriod(workspaceId, 'System');

    await createAndAcceptInvoice(10_000_000, `INV-B-${uniqueId('inv035')}`);
    await advancePeriod(workspaceId, 'System');

    await createAndAcceptInvoice(1_000_000, `INV-C-${uniqueId('inv035')}`);

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const before = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    const balanceBefore = before.balance_due_cents as number;

    const adv = await advancePeriod(workspaceId, 'System');
    expect((adv as any).period_index).toBe(5);
    const ids = ((adv as any).finance_charge_invoice_ids ?? []) as string[];
    expect(Array.isArray(ids)).toBe(true);
    expect(ids).toHaveLength(3);

    const totals: number[] = [];
    for (const id of ids) {
      const fin = await getInvoice(workspaceId, id, 'SellerAdmin');
      expect(fin.type).toBe('FINANCE_CHARGE');
      expect(fin.status).toBe('ACCEPTED');
      expect(fin.issued_period_index).toBe(5);
      expect(fin.delivered_period_index).toBe(5);
      expect(fin.accepted_period_index).toBe(5);
      expect(fin.due_period_index).toBe(6);
      expect(fin.amount_due_cents).toBe(fin.invoice_total_cents);
      totals.push(fin.invoice_total_cents as number);
    }

    totals.sort((a, b) => a - b);
    expect(totals).toEqual([12_500, 16_667, 20_833]);
    expect(totals.reduce((s, n) => s + n, 0)).toBe(50_000);

    const after = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(after.balance_due_cents).toBe(balanceBefore + 50_000);
  });

  test('INV_036: finance charge invoices recur each period while overdue (min $25 applies) and are distinct', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1, requires_po: false });

    const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `INV-${uniqueId('inv036')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(inv);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const adv1 = await advancePeriod(workspaceId, 'System');
    const f1s = ((adv1 as any).finance_charge_invoice_ids ?? []) as string[];
    expect(f1s).toHaveLength(1);
    const f1 = f1s[0];

    const before = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    const balanceBefore = before.balance_due_cents as number;

    const adv2 = await advancePeriod(workspaceId, 'System');
    expect((adv2 as any).period_index).toBe(4);
    const f2s = ((adv2 as any).finance_charge_invoice_ids ?? []) as string[];
    expect(f2s).toHaveLength(1);
    const f2 = f2s[0];
    expect(f2).not.toBe(f1);

    const fin2 = await getInvoice(workspaceId, f2, 'SellerAdmin');
    expect(fin2.type).toBe('FINANCE_CHARGE');
    expect(fin2.status).toBe('ACCEPTED');
    expect(fin2.issued_period_index).toBe(4);
    expect(fin2.delivered_period_index).toBe(4);
    expect(fin2.accepted_period_index).toBe(4);
    expect(fin2.due_period_index).toBe(5);
    expect(fin2.invoice_total_cents).toBe(2_500);
    expect(fin2.amount_due_cents).toBe(2_500);

    const financeCharges = await listInvoices(workspaceId, { customer_id: customerId, type: 'FINANCE_CHARGE' }, 'SellerAdmin');
    expect(financeCharges).toHaveLength(2);

    const after = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(after.balance_due_cents).toBe(balanceBefore + 2_500);
  });

  test('INV_037: SellerAR goodwill credit per-customer-per-period cap resets after advance_period', async () => {
    const workspace = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
    const workspaceId = workspace.workspace_id;
    const customer = await createCustomer(workspaceId, {}, 'SellerAdmin');
    const customerId = getCustomerId(customer);

    const cmA = await createCreditMemo(workspaceId, customerId, { reason: 'GOODWILL', items: [{ quantity_units: 10, unit_price_cents: 10_000 }] }, 'SellerAR');
    const cmB = await createCreditMemo(workspaceId, customerId, { reason: 'GOODWILL', items: [{ quantity_units: 10, unit_price_cents: 10_000 }] }, 'SellerAR');
    const cmC = await createCreditMemo(workspaceId, customerId, { reason: 'GOODWILL', items: [{ quantity_units: 5, unit_price_cents: 10_000 }] }, 'SellerAR');
    await issueCreditMemo(workspaceId, getCreditMemoId(cmA), 'SellerAR');
    await issueCreditMemo(workspaceId, getCreditMemoId(cmB), 'SellerAR');
    await issueCreditMemo(workspaceId, getCreditMemoId(cmC), 'SellerAR');

    const cust0 = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust0.available_credit_cents).toBe(250_000);

    await advancePeriod(workspaceId, 'System');

    const before = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    const availableBefore = before.available_credit_cents as number;

    const next = await createCreditMemo(workspaceId, customerId, { reason: 'GOODWILL', items: [{ quantity_units: 1, unit_price_cents: 10_000 }] }, 'SellerAR');
    const nextId = getCreditMemoId(next);

    await issueCreditMemo(workspaceId, nextId, 'SellerAR');

    const got = await getCreditMemo(workspaceId, nextId, 'SellerAdmin');
    expect(got.status).toBe('ISSUED');

    const after = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(after.available_credit_cents).toBe(availableBefore + 10_000);
    expect(after.balance_due_cents).toBe(0);
    expect(after.unapplied_cash_cents).toBe(0);
  });

  test('INV_501: applying a customer-level credit to a disputed invoice clamps amount_disputed_cents and can clear COLLECTIONS stage', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1, requires_po: false });

    const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `INV-501-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(inv);
    await addInvoiceLine(workspaceId, invoiceId, { description: 'L1', quantity_units: 1, unit_price_cents: 80_000 }, 'SellerAR');
    await addInvoiceLine(workspaceId, invoiceId, { description: 'L2', quantity_units: 1, unit_price_cents: 20_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    await advancePeriod(workspaceId, 'System');

    const inv1 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv1.amount_due_cents).toBe(100_000);
    const l1Id = getFirstInvoiceLineId(inv1);

    const dispute = await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: l1Id, disputed_amount_cents: 80_000 }] },
      'BuyerAP'
    );
    const disputeId = getDisputeId(dispute);
    const responded = await sellerRespond(workspaceId, disputeId, 'SellerAR');
    expect(responded.status).toBe('IN_REVIEW');

    const invDisputed = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invDisputed.amount_disputed_cents).toBe(80_000);

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const invColl = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invColl.collections_stage).toBe('COLLECTIONS');

    const cm = await createCreditMemo(workspaceId, customerId, { reason: 'GOODWILL', items: [{ quantity_units: 1, unit_price_cents: 30_000 }] }, 'SellerAR');
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAR');

    const beforeApply = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(beforeApply.available_credit_cents).toBe(30_000);

    await applyCreditMemo(workspaceId, cmId, invoiceId, 'SellerAR');

    const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter.status).toBe('ACCEPTED');
    expect(invAfter.amount_due_cents).toBe(70_000);
    expect(invAfter.amount_disputed_cents).toBe(70_000);
    expect(invAfter.collections_stage).toBe('CURRENT');
    expect(invAfter.amount_disputed_cents).toBeGreaterThanOrEqual(0);
    expect(invAfter.amount_disputed_cents).toBeLessThanOrEqual(invAfter.amount_due_cents);

    const d = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(d.status).toBe('IN_REVIEW');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');

    expect(cust.balance_due_cents).toBe(75_000);
    expect(cust.available_credit_cents).toBe(0);
    expect(cust.unapplied_cash_cents).toBe(0);

    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const sumDue = (all as any[])
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
    expect(sumDue).toBe(75_000);
    expect(sumDue).toBe(cust.balance_due_cents);
  });

  test('INV_950: payment reversal does not change PO net_billed_units', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1, requires_po: true });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 10, unit_price_cents: 10_000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId, external_invoice_ref: `INV-950-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(inv);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const pmt = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 100_000, allocations: [{ invoice_id: invoiceId, amount_cents: 100_000 }] },
      'BuyerAP'
    );
    const paymentId = getPaymentId(pmt);
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const payCleared = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(payCleared.status).toBe('CLEARED');

    const invClosed = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invClosed.status).toBe('CLOSED');
    expect(invClosed.amount_due_cents).toBe(0);

    const poAfterPay = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    expect(poAfterPay.lines[0].net_billed_units).toBe(10);
    expect(poAfterPay.lines[0].received_units).toBe(0);

    await reversePayment(workspaceId, paymentId, 'SellerAdmin').then(expectSuccess);

    const payRev = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(payRev.status).toBe('REVERSED');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('FROZEN');
    expect(cust.balance_due_cents).toBe(100_000);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);

    const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter.status).toBe('ACCEPTED');
    expect(invAfter.amount_due_cents).toBe(100_000);
    expect(invAfter.amount_disputed_cents).toBe(0);

    const poAfterRev = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    expect(poAfterRev.lines[0].net_billed_units).toBe(10);

    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const sumDue = (all as any[])
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
    expect(sumDue).toBe(100_000);
    expect(sumDue).toBe(cust.balance_due_cents);
  });
});
