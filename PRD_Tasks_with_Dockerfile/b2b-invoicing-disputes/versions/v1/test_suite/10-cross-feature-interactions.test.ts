import { postAs } from '../../../test-helpers/api-client';
import { expectErrorCode, expectSuccess } from '../../../test-helpers/assertions';
import { advanceToPeriod, setupWorkspaceCustomerContract } from '../../../test-helpers/fixtures';
import {
  acceptInvoice,
  acceptResolution,
  acknowledgePurchaseOrder,
  addInvoiceLine,
  advancePeriod,
  applyCreditMemo,
  cancelPurchaseOrder,
  closeBooks,
  createContract,
  createCustomer,
  createCreditMemo,
  createDispute,
  createInvoice,
  createPayment,
  createPurchaseOrder,
  createWorkspace,
  finalizeInvoice,
  freezeCustomer,
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
  getPayment,
  getPaymentId,
  getPurchaseOrder,
  getPurchaseOrderId,
  getWorkspace,
  issueCreditMemo,
  listInvoices,
  markPaymentCleared,
  markPaymentFailed,
  proposeResolution,
  recordReceipt,
  reversePayment,
  sendInvoice,
  suspendContract,
  closeCustomer,
  unfreezeCustomer,
  voidInvoice,
  withdrawDispute,
  writeOffInvoice,
  uniqueId
} from '../../../test-helpers/resources';

describe('Cross Feature Interactions', () => {
  test('CROSS_001: receipts can flip match_status; dispute remains active', async () => {
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
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.status).toBe('SENT');
    expect(inv0.match_status).toBe('EXCEPTION');

    const invoiceLineId = getFirstInvoiceLineId(inv0);
    const dispute = await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'MISSING_RECEIPT', items: [{ invoice_line_id: invoiceLineId, disputed_units: 10 }] },
      'BuyerAP'
    );
    const disputeId = getDisputeId(dispute);

    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);
    const invAccepted = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAccepted.status).toBe('ACCEPTED');
    expect(invAccepted.amount_disputed_cents).toBe(100_000);

    await recordReceipt(workspaceId, poId, [{ purchase_order_line_id: poLineId, received_units: 10 }], 'BuyerAP').then(expectSuccess);
    const invMatched = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invMatched.match_status).toBe('MATCHED');

    expect(invMatched.amount_disputed_cents).toBe(100_000);
    expect(disputeId).toBeDefined();
  });

  test('CROSS_002: hold override does not apply when customer has invoice in COLLECTIONS', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1 });

    const i = await createInvoice(workspaceId, customerId, { contract_id: contractId }, 'SellerAR');
    const iId = getInvoiceId(i);
    await addInvoiceLine(workspaceId, iId, { quantity_units: 5, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, iId, {}, 'SellerAR');
    await sendInvoice(workspaceId, iId, 'SellerAR');
    await acceptInvoice(workspaceId, iId, 'BuyerAP').then(expectSuccess);

    const inv = await getInvoice(workspaceId, iId, 'SellerAdmin');
    const duePeriod = inv.due_period_index as number;
    await advanceToPeriod(workspaceId, duePeriod + 3);
    const invColl = await getInvoice(workspaceId, iId, 'SellerAdmin');
    expect(invColl.collections_stage).toBe('COLLECTIONS');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('CREDIT_HOLD');

    const i2 = await createInvoice(workspaceId, customerId, { contract_id: contractId }, 'SellerAR');
    const i2Id = getInvoiceId(i2);
    await addInvoiceLine(workspaceId, i2Id, { quantity_units: 90, unit_price_cents: 10_000 }, 'SellerAR');

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${i2Id}/finalize`,
      { override_hold: true, override_billing_cap: false, final_invoice: false },
      'SellerAdmin'
    );
    await expectErrorCode(res, 'ERR_CUSTOMER_ON_HOLD');
  });

  test('CROSS_003: payment reversal voids early-pay discount and restores invoice amount_due', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 5, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.amount_due_cents).toBe(50_000);

    const payment = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 49_000, allocations: [{ invoice_id: invoiceId, amount_cents: 49_000 }] },
      'BuyerAP'
    );
    const paymentId = getPaymentId(payment);
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const invSettled = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invSettled.status).toBe('CLOSED');
    expect(invSettled.amount_due_cents).toBe(0);

    await reversePayment(workspaceId, paymentId, 'SellerAdmin').then(expectSuccess);
    const invReopened = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invReopened.amount_due_cents).toBe(50_000);
    expect(invReopened.status).not.toBe('CLOSED');
  });

  test('CROSS_004: applied credits can clear CREDIT_HOLD by reducing overdue exposure < $5k', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1 });

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 300, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const duePeriod = inv0.due_period_index as number;
    await advanceToPeriod(workspaceId, duePeriod + 1);

    const custHold = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custHold.status).toBe('CREDIT_HOLD');

    const invOverdue = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(invOverdue);
    const currentDue = invOverdue.amount_due_cents as number;

    const creditAmount = currentDue - 400_000;
    expect(creditAmount).toBe(2_600_000);

    const cm = await createCreditMemo(
      workspaceId,
      customerId,
      { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: invoiceLineId, quantity_units: 260, unit_price_cents: 10_000 }] },
      'SellerAdmin'
    );
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAdmin');
    await applyCreditMemo(workspaceId, cmId, invoiceId, 'SellerAdmin');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('ACTIVE');
  });

  test('CROSS_005: frozen customer blocks sending new invoices (ERR_CUSTOMER_FROZEN)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();

    const p = await createPayment(workspaceId, customerId, { amount_cents: 50_000 }, 'BuyerAP');
    const pId = getPaymentId(p);
    await markPaymentCleared(workspaceId, pId, 'SellerAR');
    await reversePayment(workspaceId, pId, 'SellerAdmin').then(expectSuccess);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('FROZEN');

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');

    const res = await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR');
    await expectErrorCode(res, 'ERR_CUSTOMER_FROZEN');
  });

  test('CROSS_006: escalated dispute puts customer on hold and blocks invoice finalization', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 10, unit_price_cents: 10_000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv0);
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

    const i2 = await createInvoice(workspaceId, customerId, { contract_id: contractId }, 'SellerAR');
    const i2Id = getInvoiceId(i2);
    await addInvoiceLine(workspaceId, i2Id, { quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${i2Id}/finalize`,
      { override_hold: false, override_billing_cap: false, final_invoice: false },
      'SellerAR'
    );
    await expectErrorCode(res, 'ERR_CUSTOMER_ON_HOLD');
  });

  test('CROSS_007: credit resolving PRICE_MISMATCH flips match_status and allows acceptance', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: true });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 10, unit_price_cents: 10_000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 10_600, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.match_status).toBe('EXCEPTION');
    const invoiceLineId = getFirstInvoiceLineId(inv0);

    const dispute = await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'PRICE_MISMATCH', items: [{ invoice_line_id: invoiceLineId, disputed_units: 10 }] },
      'BuyerAP'
    );
    const disputeId = getDisputeId(dispute);

    await proposeResolution(
      workspaceId,
      disputeId,
      { proposed_credit: { items: [{ invoice_line_id: invoiceLineId, quantity_units: 10, unit_price_cents: 100 }] } },
      'SellerAR'
    );

    await acceptResolution(workspaceId, disputeId, 'BuyerAP').then(expectSuccess);

    const inv1 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv1.match_status).toBe('MATCHED');

    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);
    const inv2 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv2.status).toBe('ACCEPTED');
  });

  test('CROSS_009: explicit payment allocation exceeding undisputed payable amount fails ERR_PAYMENT_EXCEEDS_ALLOWED', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 1, unit_price_cents: 10_000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 1, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);
    await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_amount_cents: 5000 }] },
      'BuyerAP'
    );

    const res = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/payments`,
      { amount_cents: 7_000, allocations: [{ invoice_id: invoiceId, amount_cents: 7_000 }] },
      'BuyerAP'
    );
    await expectErrorCode(res, 'ERR_PAYMENT_EXCEEDS_ALLOWED');
  });

  test('CROSS_010: accept_resolution fails after dispute auto-withdraws', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 1, unit_price_cents: 10_000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 1, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

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
      { proposed_credit: { items: [{ invoice_line_id: invoiceLineId, quantity_units: 1, unit_price_cents: 10_000 }] } },
      'SellerAR'
    );

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const d = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(d.status).toBe('WITHDRAWN');

    const res = await acceptResolution(workspaceId, disputeId, 'BuyerAP');
    await expectErrorCode(res, 'ERR_INVALID_STATE_TRANSITION');
  });

  test('CROSS_011: written off invoice is not payable (ERR_INVOICE_NOT_PAYABLE)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1 });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 2, unit_price_cents: 10_000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 2, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const duePeriod = inv0.due_period_index as number;
    await advanceToPeriod(workspaceId, duePeriod + 3);

    const invColl = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invColl.collections_stage).toBe('COLLECTIONS');
    expect(invColl.amount_due_cents).toBe(20_000);

    await writeOffInvoice(workspaceId, invoiceId, 'SellerAR').then(expectSuccess);

    const invClosed = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invClosed.status).toBe('CLOSED');

    const res = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/payments`,
      { amount_cents: 1000, allocations: [{ invoice_id: invoiceId, amount_cents: 1000 }] },
      'BuyerAP'
    );
    await expectErrorCode(res, 'ERR_INVOICE_NOT_PAYABLE');
  });

  test('CROSS_012: pay undisputed invoice + finance charge invoice with explicit allocations succeeds', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1 });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 10, unit_price_cents: 10_000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv0);
    await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_amount_cents: 40_000 }] },
      'BuyerAP'
    );

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');
    const adv = await advancePeriod(workspaceId, 'System');
    const financeIds = (adv as any).finance_charge_invoice_ids as string[] | undefined;
    expect(Array.isArray(financeIds)).toBe(true);
    expect(financeIds?.length).toBe(1);
    const financeInvoiceId = financeIds![0];

    const fin = await getInvoice(workspaceId, financeInvoiceId, 'SellerAdmin');
    expect(fin.amount_due_cents).toBe(2_500);

    const res = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/payments`,
      {
        amount_cents: 62_500,
        allocations: [
          { invoice_id: invoiceId, amount_cents: 60_000 },
          { invoice_id: financeInvoiceId, amount_cents: 2_500 }
        ]
      },
      'BuyerAP'
    );
    expectSuccess(res);
    const payment = res.body?.data ?? res.body;
    expect(payment.status).toBe('INITIATED');
  });

  test('CROSS_013: applying credit memo succeeds while customer is frozen from FRAUD dispute', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 1, unit_price_cents: 10_000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 1, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);
    await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'FRAUD', items: [{ invoice_line_id: invoiceLineId, disputed_units: 1 }] },
      'BuyerAP'
    );
    const custFrozen = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custFrozen.status).toBe('FROZEN');

    const cm = await createCreditMemo(
      workspaceId,
      customerId,
      { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: invoiceLineId, quantity_units: 1, unit_price_cents: 10_000 }] },
      'SellerAdmin'
    );
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAdmin');

    const res = await postAs(`/workspaces/${workspaceId}/credit_memos/${cmId}/apply`, { invoice_id: invoiceId }, 'SellerAdmin');
    expectSuccess(res);

    const invClosed = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invClosed.amount_due_cents).toBe(0);
  });

  test('CROSS_014: void fails with ERR_INVOICE_HAS_PAYMENTS when initiated payment exists', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 1, unit_price_cents: 10_000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 1, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const due = inv.amount_due_cents as number;
    await createPayment(workspaceId, customerId, { amount_cents: due, allocations: [{ invoice_id: invoiceId, amount_cents: due }] }, 'BuyerAP');

    const res = await voidInvoice(workspaceId, invoiceId, 'SellerAdmin');
    await expectErrorCode(res, 'ERR_INVOICE_HAS_PAYMENTS');
  });

  test('CROSS_015: override_hold does not bypass PO lifecycle validity (ERR_PO_NOT_OPEN)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: true });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 1, unit_price_cents: 10_000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    await cancelPurchaseOrder(workspaceId, poId, 'BuyerAP').then(expectSuccess);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 1, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/finalize`,
      { override_hold: true, override_billing_cap: false, final_invoice: false },
      'SellerAdmin'
    );
    await expectErrorCode(res, 'ERR_PO_NOT_OPEN');
  });

  test('CROSS_016: DUPLICATE_INVOICE dispute allowed in COLLECTIONS and does not freeze customer', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1 });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 1, unit_price_cents: 10_000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 1, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const duePeriod = inv0.due_period_index as number;
    await advanceToPeriod(workspaceId, duePeriod + 3);

    const invColl = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invColl.collections_stage).toBe('COLLECTIONS');
    const invoiceLineId = getFirstInvoiceLineId(invColl);

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/disputes`,
      { reason: 'DUPLICATE_INVOICE', items: [{ invoice_line_id: invoiceLineId, disputed_units: 1 }] },
      'BuyerAP'
    );
    expectSuccess(res);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).not.toBe('FROZEN');
  });

  test('CROSS_017: freeze window can elapse but credit hold persists from overdue exposure', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1 });

    const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `BIG-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(inv);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 300, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    await advanceToPeriod(workspaceId, 2);
    const custHold = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custHold.status).toBe('CREDIT_HOLD');

    const p = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 10_000, allocations: [{ invoice_id: invoiceId, amount_cents: 10_000 }] },
      'BuyerAP'
    );
    const pId = getPaymentId(p);
    await markPaymentCleared(workspaceId, pId, 'SellerAR');
    await reversePayment(workspaceId, pId, 'SellerAdmin').then(expectSuccess);

    await advanceToPeriod(workspaceId, 4);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('CREDIT_HOLD');
    expect(cust.balance_due_cents).toBe(3_050_000);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);

    const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter.amount_due_cents).toBe(3_000_000);
  });

  test('CROSS_018: accept_resolution is allowed while FROZEN, but customer remains FROZEN immediately after', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `FR-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const lineId = getFirstInvoiceLineId(inv0);
    const dispute = await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'FRAUD', items: [{ invoice_line_id: lineId, disputed_amount_cents: 10_000 }] },
      'BuyerAP'
    );
    const disputeId = getDisputeId(dispute);

    const frozen = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(frozen.status).toBe('FROZEN');

    await proposeResolution(
      workspaceId,
      disputeId,
      { proposed_credit: { items: [{ invoice_line_id: lineId, quantity_units: 1, unit_price_cents: 10_000 }] } },
      'SellerAR'
    );

    const res = await acceptResolution(workspaceId, disputeId, 'BuyerAP');
    expectSuccess(res);

    const d = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(d.status).toBe('CLOSED');

    const inv1 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv1.status).toBe('CLOSED');
    expect(inv1.amount_due_cents).toBe(0);
    expect(inv1.amount_disputed_cents).toBe(0);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('FROZEN');
    expect(cust.balance_due_cents).toBe(0);
  });

  test('CROSS_019: final true-up under suspended requires_po contract can omit PO and is NOT_APPLICABLE for matching', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: true });
    await suspendContract(workspaceId, contractId, 'SellerAdmin');

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `TU-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 15, unit_price_cents: 10_000 }, 'SellerAR');

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/finalize`,
      { override_hold: false, override_billing_cap: false, final_invoice: true },
      'SellerAdmin'
    );
    expectSuccess(res);

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('FINALIZED');
    expect(inv.purchase_order_id == null).toBe(true);
    expect(inv.match_status).toBe('NOT_APPLICABLE');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(inv.invoice_total_cents);
  });

  test('CROSS_020: explicit payment allocation exceeding received/matchable portion fails ERR_PAYMENT_EXCEEDS_ALLOWED', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: true, payment_terms_periods: 2 });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 10, unit_price_cents: 10_000, is_service: false }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    await recordReceipt(workspaceId, poId, [{ purchase_order_line_id: poLineId, received_units: 5 }], 'BuyerAP').then(expectSuccess);

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.match_status).toBe('EXCEPTION');
    expect(inv0.amount_due_cents).toBe(100_000);
    const beforeCust = await getCustomer(workspaceId, customerId, 'SellerAdmin');

    const res = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/payments`,
      { amount_cents: 100_000, allocations: [{ invoice_id: invoiceId, amount_cents: 100_000 }] },
      'BuyerAP'
    );
    await expectErrorCode(res, 'ERR_PAYMENT_EXCEEDS_ALLOWED');

    const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter.amount_due_cents).toBe(100_000);
    const afterCust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(afterCust.unapplied_cash_cents).toBe(beforeCust.unapplied_cash_cents);
    expect(afterCust.balance_due_cents).toBe(beforeCust.balance_due_cents);
  });

  test('CROSS_023: apply credit memo succeeds even when invoice was issued in a closed-books period', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `CB-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 5, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    await advancePeriod(workspaceId, 'System');
    await closeBooks(workspaceId, 'Auditor').then(expectSuccess);
    const ws0 = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(ws0.books_closed_through_period_index).toBe(0);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const lineId = getFirstInvoiceLineId(inv0);
    const cm = await createCreditMemo(
      workspaceId,
      customerId,
      { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: lineId, quantity_units: 1, unit_price_cents: 10_000 }] },
      'SellerAR'
    );
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAR');

    const before = await getCustomer(workspaceId, customerId, 'SellerAdmin');

    const res = await postAs(`/workspaces/${workspaceId}/credit_memos/${cmId}/apply`, { invoice_id: invoiceId }, 'SellerAR');
    expectSuccess(res);

    const inv1 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv1.amount_due_cents).toBe(40_000);
    const after = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(after.balance_due_cents).toBe(before.balance_due_cents - 10_000);
    expect(after.available_credit_cents).toBe(before.available_credit_cents - 10_000);

    const ws1 = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(ws1.books_closed_through_period_index).toBe(0);
  });

  test('CROSS_024: fully disputed invoice in COLLECTIONS returns to CURRENT and unblocks new invoice finalization', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1 });

    const i1 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `COLL-${uniqueId('inv')}` }, 'SellerAR');
    const i1Id = getInvoiceId(i1);
    await addInvoiceLine(workspaceId, i1Id, { quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, i1Id, {}, 'SellerAR');
    await sendInvoice(workspaceId, i1Id, 'SellerAR');
    await acceptInvoice(workspaceId, i1Id, 'BuyerAP').then(expectSuccess);

    await advanceToPeriod(workspaceId, 4);
    const invCollections = await getInvoice(workspaceId, i1Id, 'SellerAdmin');
    expect(invCollections.collections_stage).toBe('COLLECTIONS');

    const i2 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `NEW-${uniqueId('inv')}` }, 'SellerAR');
    const i2Id = getInvoiceId(i2);
    await addInvoiceLine(workspaceId, i2Id, { quantity_units: 1, unit_price_cents: 5_000 }, 'SellerAR');

    const blocked = await postAs(
      `/workspaces/${workspaceId}/invoices/${i2Id}/finalize`,
      { override_hold: false, override_billing_cap: false, final_invoice: false },
      'SellerAR'
    );
    await expectErrorCode(blocked, 'ERR_CUSTOMER_ON_HOLD');

    const lineId = getFirstInvoiceLineId(invCollections);
    await createDispute(workspaceId, i1Id, { reason: 'DUPLICATE_INVOICE', items: [{ invoice_line_id: lineId, disputed_amount_cents: 10_000 }] }, 'BuyerAP');

    const invAfterDispute = await getInvoice(workspaceId, i1Id, 'SellerAdmin');
    expect(invAfterDispute.amount_disputed_cents).toBe(10_000);
    expect(invAfterDispute.collections_stage).toBe('CURRENT');

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${i2Id}/finalize`,
      { override_hold: false, override_billing_cap: false, final_invoice: false },
      'SellerAR'
    );
    expectSuccess(res);
    const inv2 = await getInvoice(workspaceId, i2Id, 'SellerAdmin');
    expect(inv2.status).toBe('FINALIZED');
    expect(inv2.issued_period_index).toBe(4);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('ACTIVE');
    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const financeDue = (all as any[])
      .filter((i: any) => i.type === 'FINANCE_CHARGE')
      .reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
    expect(cust.balance_due_cents).toBe((invAfterDispute.amount_due_cents as number) + (inv2.amount_due_cents as number) + financeDue);
  });

  test('CROSS_025: close_books closes prior period even if current period has INITIATED payments', async () => {
    const workspace = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
    const workspaceId = workspace.workspace_id;
    const customer = await createCustomer(workspaceId, {}, 'SellerAdmin');
    const customerId = getCustomerId(customer);

    await advancePeriod(workspaceId, 'System');

    const p1 = await createPayment(workspaceId, customerId, { amount_cents: 1_000 }, 'BuyerAP');
    const p1Id = getPaymentId(p1);
    expect(p1.status).toBe('INITIATED');

    const pre = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(pre.period_index).toBe(1);
    expect(pre.books_closed_through_period_index).toBe(null);

    const res = await closeBooks(workspaceId, 'Auditor');
    expectSuccess(res);

    const ws = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(ws.period_index).toBe(1);
    expect(ws.books_closed_through_period_index).toBe(0);

    const pay = await getPayment(workspaceId, p1Id, 'SellerAdmin');
    expect(pay.status).toBe('INITIATED');
  });

  test('CROSS_026: close_books succeeds after an INITIATED payment from the closing period is cleared in the next period', async () => {
    const workspace = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
    const workspaceId = workspace.workspace_id;
    const customer = await createCustomer(workspaceId, {}, 'SellerAdmin');
    const customerId = getCustomerId(customer);

    const p0 = await createPayment(workspaceId, customerId, { amount_cents: 1_000 }, 'BuyerAP');
    const p0Id = getPaymentId(p0);
    expect(p0.status).toBe('INITIATED');

    await advancePeriod(workspaceId, 'System');
    await markPaymentCleared(workspaceId, p0Id, 'SellerAR');

    const pre = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(pre.books_closed_through_period_index).toBe(null);
    expect(pre.period_index).toBe(1);

    const res = await closeBooks(workspaceId, 'Auditor');
    expectSuccess(res);

    const ws = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(ws.books_closed_through_period_index).toBe(0);

    const pay = await getPayment(workspaceId, p0Id, 'SellerAdmin');
    expect(pay.status).toBe('CLEARED');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);
    expect(cust.unapplied_cash_cents).toBe(1_000);
  });

  test('CROSS_027: customer-level credit memo can be applied to multiple invoices until exhausted', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2, requires_po: false });

    const i1 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `I1-${uniqueId('cross27')}` }, 'SellerAR');
    const i1Id = getInvoiceId(i1);
    await addInvoiceLine(workspaceId, i1Id, { quantity_units: 3, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, i1Id, {}, 'SellerAR');
    await sendInvoice(workspaceId, i1Id, 'SellerAR');
    await acceptInvoice(workspaceId, i1Id, 'BuyerAP').then(expectSuccess);

    const i2 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `I2-${uniqueId('cross27')}` }, 'SellerAR');
    const i2Id = getInvoiceId(i2);
    await addInvoiceLine(workspaceId, i2Id, { quantity_units: 2, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, i2Id, {}, 'SellerAR');
    await sendInvoice(workspaceId, i2Id, 'SellerAR');
    await acceptInvoice(workspaceId, i2Id, 'BuyerAP').then(expectSuccess);

    const cm = await createCreditMemo(workspaceId, customerId, { reason: 'GOODWILL', items: [{ quantity_units: 4, unit_price_cents: 10_000 }] }, 'SellerAR');
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAR');
    await applyCreditMemo(workspaceId, cmId, i1Id, 'SellerAR');

    const inv1Closed = await getInvoice(workspaceId, i1Id, 'SellerAdmin');
    expect(inv1Closed.status).toBe('CLOSED');

    const snap = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(snap.available_credit_cents).toBe(10_000);
    const balanceBefore = snap.balance_due_cents as number;
    expect(balanceBefore).toBe(20_000);

    await applyCreditMemo(workspaceId, cmId, i2Id, 'SellerAR');

    const inv2 = await getInvoice(workspaceId, i2Id, 'SellerAdmin');
    expect(inv2.status).toBe('ACCEPTED');
    expect(inv2.amount_due_cents).toBe(10_000);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.available_credit_cents).toBe(0);
    expect(cust.balance_due_cents).toBe(10_000);

    const gotCm = await getCreditMemo(workspaceId, cmId, 'SellerAdmin');
    expect(gotCm.status).toBe('ISSUED');

    const inv1Now = await getInvoice(workspaceId, i1Id, 'SellerAdmin');
    const sumDue = [inv1Now, inv2].filter((i) => i.status !== 'VOIDED').reduce((s, i) => s + ((i.amount_due_cents as number) ?? 0), 0);
    expect(sumDue).toBe(cust.balance_due_cents);
  });

  test('CROSS_028: voiding a FINALIZED PO-linked invoice unwinds PO.net_billed_units and customer exposure', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: true });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { po_number: `PO-${uniqueId('cross28')}`, lines: [{ ordered_units: 10, unit_price_cents: 10_000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId }, 'SellerAR');
    const invoiceId = getInvoiceId(inv);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');

    const preInv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(preInv.status).toBe('FINALIZED');
    expect(preInv.amount_due_cents).toBe(100_000);

    const prePo = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    expect(prePo.lines[0].net_billed_units).toBe(10);

    const preCust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(preCust.balance_due_cents).toBe(100_000);

    await voidInvoice(workspaceId, invoiceId, 'SellerAR').then(expectSuccess);

    const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter.status).toBe('VOIDED');
    expect(invAfter.amount_due_cents).toBe(0);

    const poAfter = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    expect(poAfter.lines[0].net_billed_units).toBe(0);

    const custAfter = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custAfter.balance_due_cents).toBe(0);
    expect(custAfter.unapplied_cash_cents).toBe(0);
    expect(custAfter.available_credit_cents).toBe(0);
  });

  test('CROSS_029: after withdrawing a missing-receipt dispute, paying beyond matchable/received portion fails ERR_PAYMENT_EXCEEDS_ALLOWED', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: true, payment_terms_periods: 1 });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { po_number: `PO-${uniqueId('cross29')}`, lines: [{ ordered_units: 10, unit_price_cents: 10_000, is_service: false }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);
    await recordReceipt(workspaceId, poId, [{ purchase_order_line_id: poLineId, received_units: 5 }], 'BuyerAP').then(expectSuccess);

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.match_status).toBe('EXCEPTION');
    const invoiceLineId = getFirstInvoiceLineId(inv0);

    const dispute = await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'MISSING_RECEIPT', items: [{ invoice_line_id: invoiceLineId, disputed_units: 5 }] },
      'BuyerAP'
    );
    const disputeId = getDisputeId(dispute);

    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);
    const invAccepted = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAccepted.status).toBe('ACCEPTED');
    expect(invAccepted.amount_disputed_cents).toBe(50_000);

    await withdrawDispute(workspaceId, disputeId, 'BuyerAP');
    const invAfterWithdraw = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfterWithdraw.amount_disputed_cents).toBe(0);
    expect(invAfterWithdraw.match_status).toBe('EXCEPTION');

    const snap = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    const balanceBefore = snap.balance_due_cents as number;
    const unappliedBefore = snap.unapplied_cash_cents as number;

    const res = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/payments`,
      { amount_cents: 100_000, allocations: [{ invoice_id: invoiceId, amount_cents: 100_000 }] },
      'BuyerAP'
    );
    await expectErrorCode(res, 'ERR_PAYMENT_EXCEEDS_ALLOWED');

    const invFinal = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invFinal.status).toBe('ACCEPTED');
    expect(invFinal.amount_due_cents).toBe(100_000);
    expect(invFinal.amount_disputed_cents).toBe(0);

    const custAfter = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custAfter.balance_due_cents).toBe(balanceBefore);
    expect(custAfter.unapplied_cash_cents).toBe(unappliedBefore);
  });

  test('CROSS_030: credits not tied to PO-linked line do not affect price matching or PO.net_billed_units', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: true });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { po_number: `PO-${uniqueId('cross30')}`, lines: [{ ordered_units: 3, unit_price_cents: 10_000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 3, unit_price_cents: 10_501, purchase_order_line_id: poLineId }, 'SellerAR');
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 1, unit_price_cents: 1 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.match_status).toBe('EXCEPTION');
    const lines = inv0.lines as any[];
    const otherLine = lines.find((l) => l.purchase_order_line_id == null);
    if (!otherLine) throw new Error('Could not find non-PO invoice line');
    const otherLineId = otherLine.invoice_line_id ?? otherLine.id ?? otherLine.line_id;
    if (!otherLineId) throw new Error('Could not resolve invoice_line_id for non-PO line');

    const cm = await createCreditMemo(
      workspaceId,
      customerId,
      { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: otherLineId, quantity_units: 1, unit_price_cents: 1 }] },
      'SellerAR'
    );
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAR');

    const custBefore = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    const balanceBefore = custBefore.balance_due_cents as number;
    const dueBefore = (await getInvoice(workspaceId, invoiceId, 'SellerAdmin')).amount_due_cents as number;

    const poBefore = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    expect(poBefore.lines[0].net_billed_units).toBe(3);

    await applyCreditMemo(workspaceId, cmId, invoiceId, 'SellerAR');

    const inv1 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv1.match_status).toBe('EXCEPTION');
    expect(inv1.amount_due_cents).toBe(dueBefore - 1);

    const poAfter = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    expect(poAfter.lines[0].net_billed_units).toBe(3);

    const custAfter = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custAfter.balance_due_cents).toBe(balanceBefore - 1);
  });

  test('CROSS_031: cannot dispute amounts that were already credited (ERR_DISPUTE_AMOUNT_EXCEEDS_AVAILABLE)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: false });

    const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `C31-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(inv);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const lineId = getFirstInvoiceLineId(inv0);

    const cm = await createCreditMemo(
      workspaceId,
      customerId,
      { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: lineId, quantity_units: 3, unit_price_cents: 1_000 }] },
      'SellerAR'
    );
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAR');
    await applyCreditMemo(workspaceId, cmId, invoiceId, 'SellerAR');

    const invAfterCredit = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfterCredit.amount_due_cents).toBe(7_000);
    expect(invAfterCredit.amount_disputed_cents).toBe(0);

    const snap = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    const balanceBefore = snap.balance_due_cents as number;

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/disputes`,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: 9_000 }] },
      'BuyerAP'
    );
    await expectErrorCode(res, 'ERR_DISPUTE_AMOUNT_EXCEEDS_AVAILABLE');

    const invFinal = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invFinal.amount_disputed_cents).toBe(0);
    expect(invFinal.amount_due_cents).toBe(7_000);

    const custAfter = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custAfter.balance_due_cents).toBe(balanceBefore);
  });

  test('CROSS_032: CREDIT_HOLD persists until exposure < $5k (hysteresis)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1, requires_po: false });

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `C32-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 300, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.collections_stage).toBe('REMINDER');

    const hold0 = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(hold0.status).toBe('CREDIT_HOLD');

    const p = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 2_000_000, allocations: [{ invoice_id: invoiceId, amount_cents: 2_000_000 }] },
      'BuyerAP'
    );
    await markPaymentCleared(workspaceId, getPaymentId(p), 'SellerAR');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('CREDIT_HOLD');
    expect(cust.balance_due_cents).toBe(1_000_000);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);

    const inv1 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv1.amount_due_cents).toBe(1_000_000);
    expect(inv1.collections_stage).toBe('REMINDER');

    expect(inv1.amount_due_cents).toBe(cust.balance_due_cents);
  });

  test('CROSS_033: final true-up exception does not apply when invoice references a PO under suspended contract', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: true });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { po_number: `PO-${uniqueId('c33')}`, lines: [{ ordered_units: 1, unit_price_cents: 10_000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    await suspendContract(workspaceId, contractId, 'SellerAdmin');

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId, external_invoice_ref: `C33-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 1, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/finalize`,
      { override_hold: false, override_billing_cap: false, final_invoice: true },
      'SellerAdmin'
    );
    await expectErrorCode(res, 'ERR_CONTRACT_INACTIVE');

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('DRAFT');
    expect(inv.invoice_total_cents).toBe(0);
    expect(inv.issued_period_index == null).toBe(true);

    const poAfter = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    expect(poAfter.lines[0].net_billed_units).toBe(0);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(0);
  });

  test('CROSS_034: FRAUD dispute on FINANCE_CHARGE invoice is allowed and freezes customer', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1, requires_po: false });

    const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `C34-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(inv);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const adv = await advancePeriod(workspaceId, 'System');
    const financeIds = (adv as any).finance_charge_invoice_ids as string[] | undefined;
    expect(Array.isArray(financeIds)).toBe(true);
    expect(financeIds?.length).toBe(1);
    const f = financeIds![0];

    const fin = await getInvoice(workspaceId, f, 'SellerAdmin');
    expect(fin.type).toBe('FINANCE_CHARGE');
    expect(fin.status).toBe('ACCEPTED');
    expect(fin.invoice_total_cents).toBe(2_500);
    expect(fin.amount_due_cents).toBe(2_500);
    const fl = getFirstInvoiceLineId(fin);

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${f}/disputes`,
      { reason: 'FRAUD', items: [{ invoice_line_id: fl, disputed_amount_cents: 2_500 }] },
      'BuyerAP'
    );
    expectSuccess(res, 201);

    const dBody = res.body?.data ?? res.body;
    expect(dBody.status).toBe('OPEN');
    expect(dBody.reason).toBe('FRAUD');

    const finAfter = await getInvoice(workspaceId, f, 'SellerAdmin');
    expect(finAfter.status).toBe('ACCEPTED');
    expect(finAfter.amount_due_cents).toBe(2_500);
    expect(finAfter.amount_disputed_cents).toBe(2_500);
    expect(finAfter.amount_disputed_cents).toBeLessThanOrEqual(finAfter.amount_due_cents);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('FROZEN');
  });

  test('CROSS_035: reject_resolution is allowed while customer is FROZEN; dispute escalates and freeze persists', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: false });

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `C35-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const lineId = getFirstInvoiceLineId(inv0);

    const dispute = await createDispute(workspaceId, invoiceId, { reason: 'FRAUD', items: [{ invoice_line_id: lineId, disputed_amount_cents: 10_000 }] }, 'BuyerAP');
    const disputeId = getDisputeId(dispute);

    const frozen = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(frozen.status).toBe('FROZEN');

    await proposeResolution(
      workspaceId,
      disputeId,
      { proposed_credit: { items: [{ invoice_line_id: lineId, quantity_units: 1, unit_price_cents: 10_000 }] } },
      'SellerAR'
    );

    const rej = await postAs(`/workspaces/${workspaceId}/disputes/${disputeId}/reject_resolution`, {}, 'BuyerAP');
    expectSuccess(rej);

    const d = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(d.status).toBe('ESCALATED');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('FROZEN');

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.amount_disputed_cents).toBeGreaterThan(0);
    expect(inv.amount_disputed_cents).toBeLessThanOrEqual(inv.amount_due_cents);
  });

  test('CROSS_036: withdrawing an ESCALATED dispute releases disputed amount and clears CREDIT_HOLD when eligible', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2, requires_po: false });

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `C36-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.status).toBe('ACCEPTED');
    expect(inv0.due_period_index).toBe(2);
    const lineId = getFirstInvoiceLineId(inv0);

    const dispute = await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: 10_000 }] },
      'BuyerAP'
    );
    const disputeId = getDisputeId(dispute);

    await proposeResolution(
      workspaceId,
      disputeId,
      { proposed_credit: { items: [{ invoice_line_id: lineId, quantity_units: 1, unit_price_cents: 10_000 }] } },
      'SellerAR'
    );
    await postAs(`/workspaces/${workspaceId}/disputes/${disputeId}/reject_resolution`, {}, 'BuyerAP').then(expectSuccess);

    const custHold = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custHold.status).toBe('CREDIT_HOLD');

    await withdrawDispute(workspaceId, disputeId, 'BuyerAP');

    const d = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(d.status).toBe('WITHDRAWN');

    const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter.amount_disputed_cents).toBe(0);
    expect(invAfter.amount_due_cents).toBe(10_000);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('ACTIVE');
    expect(cust.balance_due_cents).toBe(10_000);
    expect(cust.balance_due_cents).toBe(invAfter.amount_due_cents);
  });

  test('CROSS_037: undisputed overdue exposure > $25k triggers CREDIT_HOLD and blocks new invoice finalization', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1, requires_po: false });

    const i1 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `C37-I1-${uniqueId('inv')}` }, 'SellerAR');
    const i2 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `C37-I2-${uniqueId('inv')}` }, 'SellerAR');
    const i1Id = getInvoiceId(i1);
    const i2Id = getInvoiceId(i2);

    await addInvoiceLine(workspaceId, i1Id, { quantity_units: 130, unit_price_cents: 10_000 }, 'SellerAR');
    await addInvoiceLine(workspaceId, i2Id, { quantity_units: 130, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, i1Id, {}, 'SellerAR');
    await finalizeInvoice(workspaceId, i2Id, {}, 'SellerAR');
    await sendInvoice(workspaceId, i1Id, 'SellerAR');
    await sendInvoice(workspaceId, i2Id, 'SellerAR');
    await acceptInvoice(workspaceId, i1Id, 'BuyerAP').then(expectSuccess);
    await acceptInvoice(workspaceId, i2Id, 'BuyerAP').then(expectSuccess);

    await advanceToPeriod(workspaceId, 2);

    const custHold = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custHold.status).toBe('CREDIT_HOLD');
    expect(custHold.balance_due_cents).toBe(2_600_000);

    const i3 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `C37-I3-${uniqueId('inv')}` }, 'SellerAR');
    const i3Id = getInvoiceId(i3);
    await addInvoiceLine(workspaceId, i3Id, { quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${i3Id}/finalize`,
      { override_hold: false, override_billing_cap: false, final_invoice: false },
      'SellerAR'
    );
    await expectErrorCode(res, 'ERR_CUSTOMER_ON_HOLD');

    const i3After = await getInvoice(workspaceId, i3Id, 'SellerAdmin');
    expect(i3After.status).toBe('DRAFT');
    expect(i3After.invoice_total_cents).toBe(0);

    const custAfter = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custAfter.status).toBe('CREDIT_HOLD');
    expect(custAfter.balance_due_cents).toBe(2_600_000);
  });

  test('CROSS_038: cancelling a PO is allowed with only DRAFT invoices, but later finalize fails ERR_PO_NOT_OPEN', async () => {
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

    const draft = await createInvoice(
      workspaceId,
      customerId,
      { contract_id: contractId, purchase_order_id: poId, external_invoice_ref: `C38-${uniqueId('inv')}` },
      'SellerAR'
    );
    const invoiceId = getInvoiceId(draft);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');

    const invDraft = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invDraft.status).toBe('DRAFT');
    expect(invDraft.invoice_total_cents).toBe(0);

    await cancelPurchaseOrder(workspaceId, poId, 'BuyerAP').then(expectSuccess);

    const poAfterCancel = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    expect(poAfterCancel.status).toBe('CANCELLED');
    const line = (poAfterCancel.lines as any[]).find((l: any) => (l.purchase_order_line_id ?? l.id ?? l.line_id) === poLineId);
    expect(line).toBeDefined();
    expect(line.received_units).toBe(0);
    expect(line.net_billed_units).toBe(0);

    const invAfterCancel = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfterCancel.status).toBe('DRAFT');
    expect(invAfterCancel.invoice_total_cents).toBe(0);

    const custAfterCancel = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custAfterCancel.balance_due_cents).toBe(0);

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/finalize`,
      { override_hold: false, override_billing_cap: false, final_invoice: false },
      'SellerAR'
    );
    await expectErrorCode(res, 'ERR_PO_NOT_OPEN');

    const invAfterFinalize = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfterFinalize.status).toBe('DRAFT');
    expect(invAfterFinalize.invoice_total_cents).toBe(0);

    const custFinal = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custFinal.balance_due_cents).toBe(0);
  });

  test('CROSS_039: SellerAR goodwill issuance is blocked when customer already exceeded period goodwill total via SellerAdmin', async () => {
    const ws = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
    const workspaceId = ws.workspace_id;
    const customer = await createCustomer(workspaceId, {}, 'SellerAdmin');
    const customerId = getCustomerId(customer);

    async function createAndIssueGoodwill(amountCents: number, role: 'SellerAdmin' | 'SellerAR') {
      const qty = amountCents / 10_000;
      if (!Number.isInteger(qty) || qty <= 0) throw new Error(`Cannot represent amount_cents=${amountCents} as qty*10000`);
      const cm = await createCreditMemo(workspaceId, customerId, { reason: 'GOODWILL', items: [{ quantity_units: qty, unit_price_cents: 10_000 }] }, role);
      const cmId = getCreditMemoId(cm);
      await issueCreditMemo(workspaceId, cmId, role);
      return cmId;
    }

    await createAndIssueGoodwill(100_000, 'SellerAdmin');
    await createAndIssueGoodwill(100_000, 'SellerAdmin');
    await createAndIssueGoodwill(100_000, 'SellerAdmin');

    const snap = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(snap.available_credit_cents).toBe(300_000);

    const gwAr = await createCreditMemo(workspaceId, customerId, { reason: 'GOODWILL', items: [{ quantity_units: 1, unit_price_cents: 10_000 }] }, 'SellerAR');
    const gwArId = getCreditMemoId(gwAr);

    const res = await postAs(`/workspaces/${workspaceId}/credit_memos/${gwArId}/issue`, {}, 'SellerAR');
    await expectErrorCode(res, 'ERR_CREDIT_EXCEEDS_AUTHORITY');

    const cmAfter = await getCreditMemo(workspaceId, gwArId, 'SellerAdmin');
    expect(cmAfter.status).toBe('DRAFT');

    const custAfter = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custAfter.available_credit_cents).toBe(300_000);
    expect(custAfter.balance_due_cents).toBe(0);
    expect(custAfter.unapplied_cash_cents).toBe(0);
  });

  test('CROSS_040: BuyerAP can record receipts while customer is FROZEN; match_status updates', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: true });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 10, unit_price_cents: 10_000, is_service: false }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId, external_invoice_ref: `C40-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(inv);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.status).toBe('SENT');
    expect(inv0.amount_due_cents).toBe(100_000);
    expect(inv0.match_status).toBe('EXCEPTION');
    expect(inv0.accepted_period_index == null).toBe(true);
    expect(inv0.due_period_index == null).toBe(true);

    const p0 = await createPayment(workspaceId, customerId, { amount_cents: 1_000 }, 'BuyerAP');
    const p0Id = getPaymentId(p0);
    await markPaymentCleared(workspaceId, p0Id, 'SellerAR');
    await reversePayment(workspaceId, p0Id, 'SellerAdmin').then(expectSuccess);

    const frozen = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(frozen.status).toBe('FROZEN');
    expect(frozen.unapplied_cash_cents).toBe(0);

    await recordReceipt(workspaceId, poId, [{ purchase_order_line_id: poLineId, received_units: 10 }], 'BuyerAP').then(expectSuccess);

    const poAfter = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const line = (poAfter.lines as any[]).find((l: any) => (l.purchase_order_line_id ?? l.id ?? l.line_id) === poLineId);
    expect(line).toBeDefined();
    expect(line.received_units).toBe(10);
    expect(line.net_billed_units).toBe(10);

    const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter.status).toBe('SENT');
    expect(invAfter.match_status).toBe('MATCHED');
    expect(invAfter.accepted_period_index == null).toBe(true);
    expect(invAfter.due_period_index == null).toBe(true);
    expect(invAfter.amount_due_cents).toBe(100_000);

    const custAfter = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custAfter.status).toBe('FROZEN');
    expect(custAfter.balance_due_cents).toBe(100_000);
    expect(custAfter.unapplied_cash_cents).toBe(0);
    expect(custAfter.available_credit_cents).toBe(0);
    expect(custAfter.balance_due_cents).toBe(invAfter.amount_due_cents);
  });

  test('CROSS_041: line-tied credit can reduce net_billed_units to received_units, making invoice MATCHED and accept-able', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: true, payment_terms_periods: 1 });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 10, unit_price_cents: 10_000, is_service: false }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    await recordReceipt(workspaceId, poId, [{ purchase_order_line_id: poLineId, received_units: 5 }], 'BuyerAP').then(expectSuccess);

    const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId, external_invoice_ref: `C41-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(inv);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.status).toBe('SENT');
    expect(inv0.match_status).toBe('EXCEPTION');
    expect(inv0.amount_due_cents).toBe(100_000);
    const invoiceLineId = getFirstInvoiceLineId(inv0);

    const cm = await createCreditMemo(
      workspaceId,
      customerId,
      { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: invoiceLineId, quantity_units: 5, unit_price_cents: 10_000 }] },
      'SellerAR'
    );
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAR');
    await applyCreditMemo(workspaceId, cmId, invoiceId, 'SellerAR');

    const invAfterCredit = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfterCredit.amount_due_cents).toBe(50_000);
    expect(invAfterCredit.match_status).toBe('MATCHED');

    const poAfter = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const line = (poAfter.lines as any[]).find((l: any) => (l.purchase_order_line_id ?? l.id ?? l.line_id) === poLineId);
    expect(line).toBeDefined();
    expect(line.received_units).toBe(5);
    expect(line.net_billed_units).toBe(5);

    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const invAccepted = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAccepted.status).toBe('ACCEPTED');
    expect(invAccepted.accepted_period_index).toBe(0);
    expect(invAccepted.due_period_index).toBe(1);
    expect(invAccepted.match_status).toBe('MATCHED');
    expect(invAccepted.amount_due_cents).toBe(50_000);
    expect(invAccepted.amount_disputed_cents).toBe(0);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(50_000);
    expect(cust.available_credit_cents).toBe(0);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.balance_due_cents).toBe(invAccepted.amount_due_cents);
  });

  test('CROSS_042: billing cap uses invoice_total_cents even after credits reduce amount_due_cents', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: false });

    const i1 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `C42-I1-${uniqueId('inv')}` }, 'SellerAR');
    const i1Id = getInvoiceId(i1);
    await addInvoiceLine(workspaceId, i1Id, { description: 'L1', quantity_units: 1, unit_price_cents: 6_000_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, i1Id, {}, 'SellerAR');

    const inv1 = await getInvoice(workspaceId, i1Id, 'SellerAdmin');
    expect(inv1.status).toBe('FINALIZED');
    expect(inv1.issued_period_index).toBe(0);
    expect(inv1.invoice_total_cents).toBe(6_000_000);
    expect(inv1.amount_due_cents).toBe(6_000_000);
    const lineId = getFirstInvoiceLineId(inv1);

    const cm = await createCreditMemo(
      workspaceId,
      customerId,
      { invoice_id: i1Id, reason: 'GOODWILL', items: [{ invoice_line_id: lineId, quantity_units: 1, unit_price_cents: 2_000_000 }] },
      'SellerAdmin'
    );
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAdmin');
    await applyCreditMemo(workspaceId, cmId, i1Id, 'SellerAdmin');

    const inv1AfterCredit = await getInvoice(workspaceId, i1Id, 'SellerAdmin');
    expect(inv1AfterCredit.invoice_total_cents).toBe(6_000_000);
    expect(inv1AfterCredit.amount_due_cents).toBe(4_000_000);

    const i2 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `C42-I2-${uniqueId('inv')}` }, 'SellerAR');
    const i2Id = getInvoiceId(i2);
    await addInvoiceLine(workspaceId, i2Id, { description: 'L2', quantity_units: 1, unit_price_cents: 5_000_000 }, 'SellerAR');

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${i2Id}/finalize`,
      { override_hold: false, override_billing_cap: false, final_invoice: false },
      'SellerAR'
    );
    await expectErrorCode(res, 'ERR_BILLING_CAP_EXCEEDED');

    const inv2 = await getInvoice(workspaceId, i2Id, 'SellerAdmin');
    expect(inv2.status).toBe('DRAFT');
    expect(inv2.invoice_total_cents).toBe(0);
    expect(inv2.issued_period_index == null).toBe(true);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(4_000_000);
    expect(cust.available_credit_cents).toBe(0);
    expect(cust.unapplied_cash_cents).toBe(0);
  });

  test('CROSS_043: unfreeze restores CREDIT_HOLD (does not bypass hold state)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: false, payment_terms_periods: 1 });

    const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `C43-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(inv);
    await addInvoiceLine(workspaceId, invoiceId, { description: 'Line', quantity_units: 300, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const hold = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(hold.status).toBe('CREDIT_HOLD');

    await freezeCustomer(workspaceId, customerId, 'MANUAL', 'SellerAdmin').then(expectSuccess);
    const frozen = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(frozen.status).toBe('FROZEN');

    await unfreezeCustomer(workspaceId, customerId, 'SellerAdmin').then(expectSuccess);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('CREDIT_HOLD');
    expect(cust.balance_due_cents).toBe(3_000_000);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);

    const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter.status).toBe('ACCEPTED');
    expect(invAfter.amount_due_cents).toBe(3_000_000);
    expect(invAfter.amount_disputed_cents).toBe(0);
    expect(invAfter.collections_stage).toBe('REMINDER');

    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const sumDue = (all as any[])
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
    expect(sumDue).toBe(3_000_000);
    expect(sumDue).toBe(cust.balance_due_cents);
  });

  test('CROSS_044: customer close fails if an active dispute exists even when invoice is fully credited closed', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();

    const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `C44-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(inv);
    await addInvoiceLine(workspaceId, invoiceId, { description: 'Line', quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.amount_due_cents).toBe(10_000);
    const lineId = getFirstInvoiceLineId(inv0);

    const dispute = await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: 10_000 }] },
      'BuyerAP'
    );
    const disputeId = getDisputeId(dispute);
    const d0 = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(d0.status).toBe('OPEN');

    const cm = await createCreditMemo(
      workspaceId,
      customerId,
      { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: lineId, quantity_units: 1, unit_price_cents: 10_000 }] },
      'SellerAdmin'
    );
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAdmin');
    await applyCreditMemo(workspaceId, cmId, invoiceId, 'SellerAdmin');

    const invAfterCredit = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfterCredit.status).toBe('CLOSED');
    expect(invAfterCredit.amount_due_cents).toBe(0);
    expect(invAfterCredit.amount_disputed_cents).toBe(0);

    const snap = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(snap.balance_due_cents).toBe(0);
    expect(snap.available_credit_cents).toBe(0);
    expect(snap.unapplied_cash_cents).toBe(0);

    const res = await closeCustomer(workspaceId, customerId, 'SellerAdmin');
    await expectErrorCode(res, 'ERR_CUSTOMER_NOT_SETTLED');

    const custAfter = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custAfter.status).toBe('ACTIVE');
    expect(custAfter.balance_due_cents).toBe(0);
    expect(custAfter.available_credit_cents).toBe(0);
    expect(custAfter.unapplied_cash_cents).toBe(0);

    const dAfter = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(dAfter.status).toBe('OPEN');

    const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter.status).toBe('CLOSED');
    expect(invAfter.amount_due_cents).toBe(0);
  });

  test('CROSS_045: withdrawing an ESCALATED dispute preserves CREDIT_HOLD via hysteresis when overdue exposure remains > $5k', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1 });

    const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `C45-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(inv);
    await addInvoiceLine(workspaceId, invoiceId, { description: 'Line', quantity_units: 100, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const lineId = getFirstInvoiceLineId(inv0);

    const dispute = await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: 1_000_000 }] },
      'BuyerAP'
    );
    const disputeId = getDisputeId(dispute);

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const dEsc = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(dEsc.status).toBe('ESCALATED');
    const custHold = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custHold.status).toBe('CREDIT_HOLD');

    await withdrawDispute(workspaceId, disputeId, 'BuyerAP');

    const d = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(d.status).toBe('WITHDRAWN');

    const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter.amount_due_cents).toBe(1_000_000);
    expect(invAfter.amount_disputed_cents).toBe(0);
    expect(invAfter.collections_stage).toBe('REMINDER');

    const custAfter = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custAfter.status).toBe('CREDIT_HOLD');
    expect(custAfter.balance_due_cents).toBe(1_000_000);

    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const sumDue = (all as any[])
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
    expect(sumDue).toBe(1_000_000);
    expect(sumDue).toBe(custAfter.balance_due_cents);
  });

  test('CROSS_046: after close_books, SellerAdmin can void FINALIZED invoice if only FAILED payments exist (no cleared payments ever)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();

    const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `C46-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(inv);
    await addInvoiceLine(workspaceId, invoiceId, { description: 'Line', quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');

    const finalized = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(finalized.status).toBe('FINALIZED');
    expect(finalized.issued_period_index).toBe(0);
    expect(finalized.amount_due_cents).toBe(10_000);

    const p = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 10_000, allocations: [{ invoice_id: invoiceId, amount_cents: 10_000 }] },
      'BuyerAP'
    );
    const paymentId = getPaymentId(p);
    await markPaymentFailed(workspaceId, paymentId, 'SellerAR');

    const payFailed = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(payFailed.status).toBe('FAILED');

    const invAfterFail = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfterFail.amount_due_cents).toBe(10_000);

    await advancePeriod(workspaceId, 'System');
    await closeBooks(workspaceId, 'Auditor').then(expectSuccess);
    const ws = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(ws.period_index).toBe(1);
    expect(ws.books_closed_through_period_index).toBe(0);

    await voidInvoice(workspaceId, invoiceId, 'SellerAdmin').then(expectSuccess);

    const invVoided = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invVoided.status).toBe('VOIDED');
    expect(invVoided.amount_due_cents).toBe(0);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(0);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);

    const w2 = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(w2.books_closed_through_period_index).toBe(0);
  });

  test('CROSS_047: issuing (but not applying) a tiny credit does not fix match exception; accept fails ERR_MATCH_EXCEPTION', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: true, payment_terms_periods: 1 });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 3, unit_price_cents: 10_000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    const invoice = await createInvoice(
      workspaceId,
      customerId,
      { contract_id: contractId, purchase_order_id: poId, external_invoice_ref: `C47-${uniqueId('inv')}` },
      'SellerAR'
    );
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 3, unit_price_cents: 10_501, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.status).toBe('SENT');
    expect(inv0.match_status).toBe('EXCEPTION');
    expect(inv0.invoice_total_cents).toBe(31_503);
    expect(inv0.amount_due_cents).toBe(31_503);
    expect(inv0.amount_disputed_cents).toBe(0);

    const invoiceLineId = getFirstInvoiceLineId(inv0);
    const cm = await createCreditMemo(
      workspaceId,
      customerId,
      { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: invoiceLineId, quantity_units: 1, unit_price_cents: 1 }] },
      'SellerAR'
    );
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAR');

    const afterIssue = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(afterIssue.available_credit_cents).toBe(1);

    const res = await acceptInvoice(workspaceId, invoiceId, 'BuyerAP');
    await expectErrorCode(res, 'ERR_MATCH_EXCEPTION');

    const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter.status).toBe('SENT');
    expect(invAfter.match_status).toBe('EXCEPTION');
    expect(invAfter.accepted_period_index == null).toBe(true);
    expect(invAfter.due_period_index == null).toBe(true);
    expect(invAfter.amount_due_cents).toBe(31_503);
    expect(invAfter.amount_disputed_cents).toBe(0);

    const cmAfter = await getCreditMemo(workspaceId, cmId, 'SellerAdmin');
    expect(cmAfter.status).toBe('ISSUED');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(31_503);
    expect(cust.available_credit_cents).toBe(1);
    expect(cust.unapplied_cash_cents).toBe(0);

    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const sumDue = (all as any[])
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
    expect(sumDue).toBe(31_503);
    expect(sumDue).toBe(cust.balance_due_cents);
  });

  test('CROSS_048: voided invoice still blocks PO cancel (ERR_PO_HAS_INVOICES)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: true });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 10, unit_price_cents: 10_000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    const draft = await createInvoice(
      workspaceId,
      customerId,
      { contract_id: contractId, purchase_order_id: poId, external_invoice_ref: `C48-${uniqueId('inv')}` },
      'SellerAR'
    );
    const invoiceId = getInvoiceId(draft);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');

    const invFinalized = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invFinalized.status).toBe('FINALIZED');
    expect(invFinalized.amount_due_cents).toBe(100_000);

    const poAfterFinalize = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    expect(poAfterFinalize.lines[0].net_billed_units).toBe(10);

    await voidInvoice(workspaceId, invoiceId, 'SellerAR').then(expectSuccess);

    const invVoided = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invVoided.status).toBe('VOIDED');
    expect(invVoided.amount_due_cents).toBe(0);

    const poAfterVoid = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    expect(poAfterVoid.lines[0].net_billed_units).toBe(0);

    const custAfterVoid = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custAfterVoid.balance_due_cents).toBe(0);

    const res = await cancelPurchaseOrder(workspaceId, poId, 'BuyerAP');
    await expectErrorCode(res, 'ERR_PO_HAS_INVOICES');

    const poStill = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    expect(poStill.status).toBe('OPEN');
    expect(poStill.lines[0].received_units).toBe(0);
    expect(poStill.lines[0].net_billed_units).toBe(0);

    const invStill = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invStill.status).toBe('VOIDED');
    expect(invStill.amount_due_cents).toBe(0);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(0);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);

    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const sumDue = (all as any[])
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
    expect(sumDue).toBe(0);
    expect(sumDue).toBe(cust.balance_due_cents);
  });

  test('CROSS_049: max receipt (1% over) still leaves invoice EXCEPTION when billed_units > received_units', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: true, payment_terms_periods: 1 });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 100, unit_price_cents: 10_000, is_service: false }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    const invoice = await createInvoice(
      workspaceId,
      customerId,
      { contract_id: contractId, purchase_order_id: poId, external_invoice_ref: `C49-${uniqueId('inv')}` },
      'SellerAR'
    );
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 102, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.status).toBe('SENT');
    expect(inv0.match_status).toBe('EXCEPTION');
    expect(inv0.amount_due_cents).toBe(1_020_000);
    expect(inv0.accepted_period_index == null).toBe(true);
    expect(inv0.due_period_index == null).toBe(true);

    const poBefore = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    expect(poBefore.lines[0].received_units).toBe(0);
    expect(poBefore.lines[0].net_billed_units).toBe(102);

    await recordReceipt(workspaceId, poId, [{ purchase_order_line_id: poLineId, received_units: 101 }], 'BuyerAP').then(expectSuccess);

    const poAfter = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    expect(poAfter.lines[0].received_units).toBe(101);
    expect(poAfter.lines[0].net_billed_units).toBe(102);

    const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter.status).toBe('SENT');
    expect(invAfter.match_status).toBe('EXCEPTION');
    expect(invAfter.accepted_period_index == null).toBe(true);
    expect(invAfter.due_period_index == null).toBe(true);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(1_020_000);
  });

  test('CROSS_050: acceptance succeeds when the quantity exception portion is covered by an active dispute', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: true, payment_terms_periods: 1 });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 100, unit_price_cents: 10_000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    const invoice = await createInvoice(
      workspaceId,
      customerId,
      { contract_id: contractId, purchase_order_id: poId, external_invoice_ref: `C50-${uniqueId('inv')}` },
      'SellerAR'
    );
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 103, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.status).toBe('SENT');
    expect(inv0.match_status).toBe('EXCEPTION');
    expect(inv0.amount_due_cents).toBe(1_030_000);
    const invoiceLineId = getFirstInvoiceLineId(inv0);

    const dispute = await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_units: 1 }] },
      'BuyerAP'
    );
    const disputeId = getDisputeId(dispute);

    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const invAccepted = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAccepted.status).toBe('ACCEPTED');
    expect(invAccepted.accepted_period_index).toBe(0);
    expect(invAccepted.due_period_index).toBe(1);
    expect(invAccepted.match_status).toBe('EXCEPTION');
    expect(invAccepted.amount_due_cents).toBe(1_030_000);
    expect(invAccepted.amount_disputed_cents).toBe(10_000);

    const d = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(d.status).toBe('OPEN');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(1_030_000);
    expect(invAccepted.amount_disputed_cents).toBeGreaterThanOrEqual(0);
    expect(invAccepted.amount_disputed_cents).toBeLessThanOrEqual(invAccepted.amount_due_cents);
  });

  test('CROSS_051: write_off succeeds even after close_books and resets collections_stage', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1, requires_po: false });

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `C51-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 15, unit_price_cents: 1_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    await advanceToPeriod(workspaceId, 1);
    await closeBooks(workspaceId, 'Auditor').then(expectSuccess);
    const wsClosed = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(wsClosed.period_index).toBe(1);
    expect(wsClosed.books_closed_through_period_index).toBe(0);

    await advanceToPeriod(workspaceId, 4);
    const invColl = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invColl.collections_stage).toBe('COLLECTIONS');
    expect(invColl.amount_due_cents).toBe(15_000);
    expect(invColl.amount_disputed_cents).toBe(0);

    await writeOffInvoice(workspaceId, invoiceId, 'SellerAR').then(expectSuccess);

    const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter.status).toBe('CLOSED');
    expect(invAfter.amount_due_cents).toBe(0);
    expect(invAfter.amount_disputed_cents).toBe(0);
    expect(invAfter.collections_stage).toBe('CURRENT');

    const w = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(w.period_index).toBe(4);
    expect(w.books_closed_through_period_index).toBe(0);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(5_000);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);

    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const sumDue = (all as any[])
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
    expect(sumDue).toBe(5_000);
    expect(sumDue).toBe(cust.balance_due_cents);
  });

  test('CROSS_052: acceptance succeeds when the price exception portion is covered by an active dispute', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: true, payment_terms_periods: 1 });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 10, unit_price_cents: 10_000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    const invoice = await createInvoice(
      workspaceId,
      customerId,
      { contract_id: contractId, purchase_order_id: poId, external_invoice_ref: `C52-${uniqueId('inv')}` },
      'SellerAR'
    );
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 10_600, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.status).toBe('SENT');
    expect(inv0.match_status).toBe('EXCEPTION');
    expect(inv0.amount_due_cents).toBe(106_000);
    const invoiceLineId = getFirstInvoiceLineId(inv0);

    const dispute = await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'PRICE_MISMATCH', items: [{ invoice_line_id: invoiceLineId, disputed_amount_cents: 1_000 }] },
      'BuyerAP'
    );
    const disputeId = getDisputeId(dispute);

    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const invAccepted = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAccepted.status).toBe('ACCEPTED');
    expect(invAccepted.accepted_period_index).toBe(0);
    expect(invAccepted.due_period_index).toBe(1);
    expect(invAccepted.match_status).toBe('EXCEPTION');
    expect(invAccepted.amount_due_cents).toBe(106_000);
    expect(invAccepted.amount_disputed_cents).toBe(1_000);

    const d = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(d.status).toBe('OPEN');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(106_000);
    expect(invAccepted.amount_disputed_cents).toBeGreaterThanOrEqual(0);
    expect(invAccepted.amount_disputed_cents).toBeLessThanOrEqual(invAccepted.amount_due_cents);
  });

  test('CROSS_053: SellerAdmin can finalize <=$10k invoice under CREDIT_HOLD via override_hold; hold persists from ESCALATED dispute', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2, requires_po: false });

    const i1 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `C53-I1-${uniqueId('inv')}` }, 'SellerAR');
    const i1Id = getInvoiceId(i1);
    await addInvoiceLine(workspaceId, i1Id, { quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, i1Id, {}, 'SellerAR');
    await sendInvoice(workspaceId, i1Id, 'SellerAR');
    await acceptInvoice(workspaceId, i1Id, 'BuyerAP').then(expectSuccess);

    const inv1 = await getInvoice(workspaceId, i1Id, 'SellerAdmin');
    const lineId = getFirstInvoiceLineId(inv1);

    const dispute = await createDispute(
      workspaceId,
      i1Id,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: 1_000 }] },
      'BuyerAP'
    );
    const disputeId = getDisputeId(dispute);

    await proposeResolution(
      workspaceId,
      disputeId,
      { proposed_credit: { items: [{ invoice_line_id: lineId, quantity_units: 1, unit_price_cents: 1_000 }] } },
      'SellerAR'
    );

    await postAs(`/workspaces/${workspaceId}/disputes/${disputeId}/reject_resolution`, {}, 'BuyerAP').then(expectSuccess);

    const d = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(d.status).toBe('ESCALATED');

    const custHold = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custHold.status).toBe('CREDIT_HOLD');

    const existing = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    expect((existing as any[]).some((i: any) => i.collections_stage === 'COLLECTIONS')).toBe(false);

    const i2 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `C53-I2-${uniqueId('inv')}` }, 'SellerAR');
    const i2Id = getInvoiceId(i2);
    await addInvoiceLine(workspaceId, i2Id, { quantity_units: 90, unit_price_cents: 10_000 }, 'SellerAR');

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${i2Id}/finalize`,
      { override_hold: true, override_billing_cap: false, final_invoice: false },
      'SellerAdmin'
    );
    expectSuccess(res);

    const inv2 = await getInvoice(workspaceId, i2Id, 'SellerAdmin');
    expect(inv2.status).toBe('FINALIZED');
    expect(inv2.issued_period_index).toBe(0);
    expect(inv2.invoice_total_cents).toBe(900_000);
    expect(inv2.amount_due_cents).toBe(900_000);
    expect(inv2.amount_disputed_cents).toBe(0);
    expect(inv2.match_status).toBe('NOT_APPLICABLE');

    const dAfter = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(dAfter.status).toBe('ESCALATED');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('CREDIT_HOLD');
    expect(cust.balance_due_cents).toBe(910_000);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);

    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const sumDue = (all as any[])
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
    expect(sumDue).toBe(910_000);
    expect(sumDue).toBe(cust.balance_due_cents);
  });

  test('CROSS_054: BuyerAP can accept invoices while customer is on CREDIT_HOLD', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1, requires_po: false });

    const iHold = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `C54-HOLD-${uniqueId('inv')}` }, 'SellerAR');
    const iHoldId = getInvoiceId(iHold);
    await addInvoiceLine(workspaceId, iHoldId, { quantity_units: 260, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, iHoldId, {}, 'SellerAR');
    await sendInvoice(workspaceId, iHoldId, 'SellerAR');
    await acceptInvoice(workspaceId, iHoldId, 'BuyerAP').then(expectSuccess);

    await advancePeriod(workspaceId, 'System');

    const iSent = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `C54-SENT-${uniqueId('inv')}` }, 'SellerAR');
    const iSentId = getInvoiceId(iSent);
    await addInvoiceLine(workspaceId, iSentId, { quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, iSentId, {}, 'SellerAR');
    await sendInvoice(workspaceId, iSentId, 'SellerAR');

    const sent0 = await getInvoice(workspaceId, iSentId, 'SellerAdmin');
    expect(sent0.status).toBe('SENT');
    expect(sent0.delivered_period_index).toBe(1);
    expect(sent0.match_status).toBe('NOT_APPLICABLE');
    expect(sent0.accepted_period_index == null).toBe(true);

    await advancePeriod(workspaceId, 'System');

    const invHold = await getInvoice(workspaceId, iHoldId, 'SellerAdmin');
    expect(invHold.collections_stage).toBe('REMINDER');

    const custHold = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custHold.status).toBe('CREDIT_HOLD');

    const sentPre = await getInvoice(workspaceId, iSentId, 'SellerAdmin');
    expect(sentPre.status).toBe('SENT');
    expect(sentPre.accepted_period_index == null).toBe(true);
    expect(sentPre.due_period_index == null).toBe(true);

    await acceptInvoice(workspaceId, iSentId, 'BuyerAP').then(expectSuccess);

    const sentAfter = await getInvoice(workspaceId, iSentId, 'SellerAdmin');
    expect(sentAfter.status).toBe('ACCEPTED');
    expect(sentAfter.accepted_period_index).toBe(2);
    expect(sentAfter.due_period_index).toBe(3);
    expect(sentAfter.delivered_period_index).toBe(1);
    expect(sentAfter.match_status).toBe('NOT_APPLICABLE');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('CREDIT_HOLD');
    expect(cust.balance_due_cents).toBe(2_610_000);

    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const sumDue = (all as any[])
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
    expect(sumDue).toBe(2_610_000);
    expect(sumDue).toBe(cust.balance_due_cents);
  });

  test('CROSS_101: close_books succeeds even if customer is FROZEN due to a REVERSED payment (no pending INITIATED payments)', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2, requires_po: false });

    const p0 = await createPayment(workspaceId, customerId, { amount_cents: 1_000 }, 'BuyerAP');
    const p0Id = getPaymentId(p0);
    await markPaymentCleared(workspaceId, p0Id, 'SellerAR');
    await reversePayment(workspaceId, p0Id, 'SellerAdmin').then(expectSuccess);

    const frozen = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(frozen.status).toBe('FROZEN');
    expect(frozen.balance_due_cents).toBe(0);
    expect(frozen.unapplied_cash_cents).toBe(0);
    expect(frozen.available_credit_cents).toBe(0);

    await advancePeriod(workspaceId, 'System');
    const ws1 = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(ws1.period_index).toBe(1);
    expect(ws1.books_closed_through_period_index == null).toBe(true);

    await closeBooks(workspaceId, 'Auditor').then(expectSuccess);

    const wsClosed = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(wsClosed.period_index).toBe(1);
    expect(wsClosed.books_closed_through_period_index).toBe(0);

    const pay = await getPayment(workspaceId, p0Id, 'SellerAdmin');
    expect(pay.status).toBe('REVERSED');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('FROZEN');
    expect(cust.balance_due_cents).toBe(0);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);

    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const sumDue = (all as any[])
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
    expect(sumDue).toBe(0);
    expect(sumDue).toBe(cust.balance_due_cents);
  });
});
