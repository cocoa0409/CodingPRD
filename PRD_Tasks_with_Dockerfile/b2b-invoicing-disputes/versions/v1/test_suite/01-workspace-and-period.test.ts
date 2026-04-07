import { expectErrorCode, expectSuccess } from '../../../test-helpers/assertions';
import { createSentMatchedInvoice, setupWorkspaceCustomerContract } from '../../../test-helpers/fixtures';
import {
  acceptInvoice,
  addInvoiceLine,
  advancePeriod,
  closeBooks,
  createCustomer,
  createDispute,
  createInvoice,
  createPayment,
  createPurchaseOrder,
  createWorkspace,
  finalizeInvoice,
  getCustomer,
  getCustomerId,
  getDispute,
  getDisputeId,
  getFirstInvoiceLineId,
  getFirstPurchaseOrderLineId,
  getInvoice,
  getInvoiceId,
  getPayment,
  getPaymentId,
  getPurchaseOrder,
  getPurchaseOrderId,
  getWorkspace,
  markPaymentCleared,
  proposeResolution,
  recordReceipt,
  recompute,
  sendInvoice,
  sellerRespond,
  uniqueId
} from '../../../test-helpers/resources';

describe('Workspace and Period Tests', () => {
  test('WS_001: GET workspace shows initial period fields', async () => {
    const workspace = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');

    const got = await getWorkspace(workspace.workspace_id, 'SellerAdmin');
    expect(got.period_index).toBe(0);
    expect(got.books_closed_through_period_index).toBe(null);
    expect(got.currency).toBe('USD');
  });

  test('WS_002: advance_period increments period_index', async () => {
    const workspace = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');

    await advancePeriod(workspace.workspace_id, 'System');
    const got = await getWorkspace(workspace.workspace_id, 'SellerAdmin');
    expect(got.period_index).toBe(1);
    expect(got.books_closed_through_period_index).toBe(null);
  });

  test('WS_003: advance_period deems acceptance for SENT+MATCHED invoice with no disputes', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2, requires_po: false });

    const { invoiceId } = await createSentMatchedInvoice({ workspaceId, customerId, contractId, isService: true });

    await advancePeriod(workspaceId, 'System');

    await advancePeriod(workspaceId, 'System');
    const w = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(w.period_index).toBe(2);

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('ACCEPTED');
    expect(inv.accepted_period_index).toBe(1);
    expect(inv.due_period_index).toBe(3);
  });

  test('WS_004: advance_period does not deem accept if invoice is still EXCEPTION', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: true });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 10, unit_price_cents: 10000, is_service: false }] },
      'BuyerAP'
    );
    const purchaseOrderId = getPurchaseOrderId(po);
    const fullPo = await getPurchaseOrder(workspaceId, purchaseOrderId);
    const poLineId = getFirstPurchaseOrderLineId(fullPo);

    const receiptRes = await recordReceipt(workspaceId, purchaseOrderId, [{ purchase_order_line_id: poLineId, received_units: 5 }], 'BuyerAP');
    expectSuccess(receiptRes);

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: purchaseOrderId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, {
      quantity_units: 10,
      unit_price_cents: 10000,
      purchase_order_line_id: poLineId
    });
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');

    await advancePeriod(workspaceId, 'System');

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('SENT');
    expect(inv.match_status).toBe('EXCEPTION');
    expect(inv.accepted_period_index == null).toBe(true);
    expect(inv.due_period_index == null).toBe(true);
  });

  test('WS_005: OPEN dispute auto-escalates on period advance if no seller response', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const { invoiceId } = await createSentMatchedInvoice({ workspaceId, customerId, contractId, isService: true });

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);

    const dispute = await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_units: 1 }] },
      'BuyerAP'
    );
    const disputeId = getDisputeId(dispute);

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const d = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(d.status).toBe('ESCALATED');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('CREDIT_HOLD');
  });

  test('WS_006: PROPOSED dispute does not withdraw after first period advance', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const { invoiceId } = await createSentMatchedInvoice({ workspaceId, customerId, contractId, isService: true });

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);

    const dispute = await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_units: 1 }] },
      'BuyerAP'
    );
    const disputeId = getDisputeId(dispute);

    await proposeResolution(
      workspaceId,
      disputeId,
      { proposed_credit: { items: [{ invoice_line_id: invoiceLineId, quantity_units: 1, unit_price_cents: 10000 }] } },
      'SellerAR'
    );

    await advancePeriod(workspaceId, 'System');

    const d = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(d.status).toBe('PROPOSED');
  });

  test('WS_007: once withdrawn, dispute stays stable across later period advances', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const { invoiceId } = await createSentMatchedInvoice({ workspaceId, customerId, contractId, isService: true });

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);

    const dispute = await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_units: 1 }] },
      'BuyerAP'
    );
    const disputeId = getDisputeId(dispute);

    await proposeResolution(
      workspaceId,
      disputeId,
      { proposed_credit: { items: [{ invoice_line_id: invoiceLineId, quantity_units: 1, unit_price_cents: 10000 }] } },
      'SellerAR'
    );

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const stillWithdrawn = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(stillWithdrawn.status).toBe('WITHDRAWN');
  });

  test('WS_008: close_books fails if closing period has INITIATED payments', async () => {
    const workspace = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
    const workspaceId = workspace.workspace_id;
    const customer = await createCustomer(workspaceId);
    const customerId = getCustomerId(customer);

    const payment = await createPayment(workspaceId, customerId, { amount_cents: 50000 }, 'BuyerAP');
    const paymentId = getPaymentId(payment);
    await advancePeriod(workspaceId, 'System');

    const res = await closeBooks(workspaceId, 'Auditor');
    await expectErrorCode(res, 'ERR_PERIOD_HAS_PENDING_PAYMENTS');

    const w = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(w.books_closed_through_period_index).toBe(null);
    const p = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(p.status).toBe('INITIATED');
  });

  test('WS_009: close_books succeeds when closing period has no pending payments', async () => {
    const workspace = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
    const workspaceId = workspace.workspace_id;
    const customer = await createCustomer(workspaceId);
    const customerId = getCustomerId(customer);

    const payment = await createPayment(workspaceId, customerId, { amount_cents: 50000 }, 'BuyerAP');
    const paymentId = getPaymentId(payment);
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    await advancePeriod(workspaceId, 'System');

    const res = await closeBooks(workspaceId, 'Auditor');
    expectSuccess(res);
    const got = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(got.books_closed_through_period_index).toBe(0);
  });

  test('WS_010: close_books fails when there is no newly completed period to close', async () => {
    const workspace = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
    const workspaceId = workspace.workspace_id;

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const firstClose = await closeBooks(workspaceId, 'Auditor');
    expectSuccess(firstClose);
    const afterFirst = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(afterFirst.books_closed_through_period_index).toBe(1);

    const secondClose = await closeBooks(workspaceId, 'Auditor');
    await expectErrorCode(secondClose, 'ERR_INVALID_STATE_TRANSITION');
    const afterSecond = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(afterSecond.books_closed_through_period_index).toBe(1);
  });

  test('WS_011: recompute succeeds and returns integrity_status OK', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });
    const { invoiceId } = await createSentMatchedInvoice({ workspaceId, customerId, contractId, isService: true });

    const acceptRes = await acceptInvoice(workspaceId, invoiceId, 'BuyerAP');
    expectSuccess(acceptRes);

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const amountDue = inv.amount_due_cents as number;

    const payment = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: amountDue, allocations: [{ invoice_id: invoiceId, amount_cents: amountDue }] },
      'BuyerAP'
    );
    const paymentId = getPaymentId(payment);
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const res = await recompute(workspaceId, 'SellerAdmin');
    expectSuccess(res);
    const body = res.body?.data ?? res.body;
    expect(body.integrity_status).toBe('OK');

    expect(body.period_index).toBe(0);
    expect(body.books_closed_through_period_index ?? null).toBe(null);
  });

  test('WS_013: dispute does not auto-escalate if seller responded', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const { invoiceId } = await createSentMatchedInvoice({ workspaceId, customerId, contractId, isService: true });

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);

    const dispute = await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_units: 1 }] },
      'BuyerAP'
    );
    const disputeId = getDisputeId(dispute);
    await sellerRespond(workspaceId, disputeId, 'SellerAR');

    await advancePeriod(workspaceId, 'System');

    const d = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(d.status).toBe('IN_REVIEW');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('ACTIVE');
  });

  test('WS_014: due_period_index remains stable after period advance', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });
    const { invoiceId } = await createSentMatchedInvoice({ workspaceId, customerId, contractId, isService: true });

    const acceptRes = await acceptInvoice(workspaceId, invoiceId, 'BuyerAP');
    expectSuccess(acceptRes);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.due_period_index).toBe(inv0.accepted_period_index + 2);

    await advancePeriod(workspaceId, 'System');

    const inv1 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv1.due_period_index).toBe(inv0.due_period_index);
  });

  test('WS_015: accepting an already-deemed-accepted invoice fails with ERR_INVALID_STATE_TRANSITION', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const { invoiceId } = await createSentMatchedInvoice({ workspaceId, customerId, contractId, isService: true });

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const before = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(before.status).toBe('ACCEPTED');
    const acceptedPeriodBefore = before.accepted_period_index;

    const res = await acceptInvoice(workspaceId, invoiceId, 'BuyerAP');
    await expectErrorCode(res, 'ERR_INVALID_STATE_TRANSITION');

    const after = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(after.status).toBe('ACCEPTED');
    expect(after.accepted_period_index).toBe(acceptedPeriodBefore);
  });

  test('WS_016: invoice is not deemed accepted if match_status is EXCEPTION at period close', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2, requires_po: true });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { po_number: `PO-${uniqueId('ws16')}`, lines: [{ ordered_units: 10, unit_price_cents: 10_000, is_service: false }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    const receiptRes = await recordReceipt(workspaceId, poId, [{ purchase_order_line_id: poLineId, received_units: 5 }], 'BuyerAP');
    expectSuccess(receiptRes);

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 10_000, purchase_order_line_id: poLineId });
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.status).toBe('SENT');
    expect(inv0.match_status).toBe('EXCEPTION');

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const inv1 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv1.status).toBe('SENT');
    expect(inv1.accepted_period_index == null).toBe(true);
    expect(inv1.due_period_index == null).toBe(true);
  });

  test('TRANS_006: deemed acceptance is deferred by delivered_period_index gate', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1, requires_po: true });

    await advancePeriod(workspaceId, 'System');

    const { invoiceId } = await createSentMatchedInvoice({ workspaceId, customerId, contractId, isService: true });
    const sent = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(sent.status).toBe('SENT');
    expect(sent.delivered_period_index).toBe(1);
    expect(sent.accepted_period_index == null).toBe(true);

    await advancePeriod(workspaceId, 'System');
    const stillSent = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(stillSent.status).toBe('SENT');
    expect(stillSent.accepted_period_index == null).toBe(true);

    await advancePeriod(workspaceId, 'System');
    const accepted = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(accepted.status).toBe('ACCEPTED');
    expect(accepted.accepted_period_index).toBe(2);
    expect(accepted.due_period_index).toBe(3);
    expect(accepted.delivered_period_index).toBe(1);
  });

  test('WS_018: close_books fails when period_index is 0 (nothing to close)', async () => {
    const workspace = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');

    const res = await closeBooks(workspace.workspace_id, 'Auditor');
    await expectErrorCode(res, 'ERR_INVALID_STATE_TRANSITION');
    const got = await getWorkspace(workspace.workspace_id, 'SellerAdmin');
    expect(got.period_index).toBe(0);
    expect(got.books_closed_through_period_index).toBe(null);
  });
});
