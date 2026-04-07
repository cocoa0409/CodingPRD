import { postAs } from '../../../test-helpers/api-client';
import { expectErrorCode, expectSuccess } from '../../../test-helpers/assertions';
import { setupWorkspaceCustomerContract } from '../../../test-helpers/fixtures';
import {
  acceptInvoice,
  activateContract,
  advancePeriod,
  closeBooks,
  createContract,
  createCustomer,
  createDispute,
  createInvoice,
  createPayment,
  createPurchaseOrder,
  createWorkspace,
  finalizeInvoice,
  getContractId,
  getCreditMemo,
  getDispute,
  getDisputeId,
  getCustomer,
  getCustomerId,
  getFirstInvoiceLineId,
  getFirstPurchaseOrderLineId,
  getInvoice,
  getInvoiceId,
  getPayment,
  getPaymentId,
  getPurchaseOrder,
  getPurchaseOrderId,
  getWorkspace,
  listInvoices,
  listCreditMemos,
  markPaymentCleared,
  markPaymentFailed,
  reversePayment,
  sendInvoice,
  uniqueId,
  writeOffInvoice
} from '../../../test-helpers/resources';

describe('Payment Intake and Allocation Tests', () => {
  async function createAcceptedInvoice(params: { workspaceId: string; customerId: string; contractId: string; amountDueCents: number }) {
    if (params.amountDueCents <= 0) throw new Error(`amountDueCents must be > 0. Got: ${params.amountDueCents}`);

    const unitPrice =
      params.amountDueCents % 10_000 === 0 ? 10_000 : (params.amountDueCents % 1_000 === 0 ? 1_000 : 1);
    const qty = params.amountDueCents / unitPrice;
    if (!Number.isInteger(qty) || qty <= 0) {
      throw new Error(`Could not factor amountDueCents=${params.amountDueCents} into integer qty with unitPrice=${unitPrice}`);
    }

    const invoice = await createInvoice(params.workspaceId, params.customerId, { contract_id: params.contractId, external_invoice_ref: `INV-${uniqueId('ext')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await postAs(
      `/workspaces/${params.workspaceId}/invoices/${invoiceId}/lines`,
      { description: 'Line', quantity_units: qty, unit_price_cents: unitPrice },
      'SellerAR'
    ).then(expectSuccess);
    await finalizeInvoice(params.workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(params.workspaceId, invoiceId, 'SellerAR');
    await acceptInvoice(params.workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);
    return invoiceId;
  }

  function extractListArray(value: any): any[] {
    if (Array.isArray(value)) return value;
    if (Array.isArray(value?.items)) return value.items;
    if (Array.isArray(value?.data)) return value.data;
    if (Array.isArray(value?.credit_memos)) return value.credit_memos;
    return [];
  }

  async function findEarlyPayDiscountCreditMemo(workspaceId: string, customerId: string) {
    const list = await listCreditMemos(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const arr = extractListArray(list);
    return arr.find((cm) => {
      const type = cm?.type ?? cm?.credit_memo_type ?? cm?.reason;
      return type === 'EARLY_PAY_DISCOUNT';
    });
  }

  test('PAY_001: create payment with allocations reserves allocation in INITIATED', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 50_000 });

    const payment = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 50_000, allocations: [{ invoice_id: invoiceId, amount_cents: 50_000 }] },
      'BuyerAP'
    );
    expect(payment.status).toBe('INITIATED');
    const reserved = payment.allocations ?? payment.reserved_allocations ?? payment.reserved ?? [];
    expect(Array.isArray(reserved)).toBe(true);
    expect(reserved.length).toBeGreaterThan(0);
    expect(reserved[0].invoice_id).toBe(invoiceId);
    expect(reserved[0].amount_cents).toBe(50_000);
  });

  test('PAY_002: second initiated payment cannot reserve same balance (ERR_PAYMENT_EXCEEDS_ALLOWED)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 50_000 });

    await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 50_000, allocations: [{ invoice_id: invoiceId, amount_cents: 50_000 }] },
      'BuyerAP'
    );

    const res = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/payments`,
      { amount_cents: 10_000, allocations: [{ invoice_id: invoiceId, amount_cents: 10_000 }] },
      'BuyerAP'
    );
    await expectErrorCode(res, 'ERR_PAYMENT_EXCEEDS_ALLOWED');
  });

  test('PAY_003: failed payments release reservations (second payment succeeds)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 50_000 });

    const p1 = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 50_000, allocations: [{ invoice_id: invoiceId, amount_cents: 50_000 }] },
      'BuyerAP'
    );
    await markPaymentFailed(workspaceId, getPaymentId(p1), 'SellerAR');

    const res = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/payments`,
      { amount_cents: 10_000, allocations: [{ invoice_id: invoiceId, amount_cents: 10_000 }] },
      'BuyerAP'
    );
    expectSuccess(res);
  });

  test('PAY_004: mark_cleared sets payment CLEARED and closes invoice', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 50_000 });

    const p = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 50_000, allocations: [{ invoice_id: invoiceId, amount_cents: 50_000 }] },
      'BuyerAP'
    );
    const paymentId = getPaymentId(p);

    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');
    const payment = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(payment.status).toBe('CLEARED');

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.amount_due_cents).toBe(0);
    expect(inv.status).toBe('CLOSED');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(0);
  });

  test('PAY_005: mark_failed sets payment FAILED and does not change invoice amount_due', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 50_000 });

    const p = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 50_000, allocations: [{ invoice_id: invoiceId, amount_cents: 50_000 }] },
      'BuyerAP'
    );
    const paymentId = getPaymentId(p);

    await markPaymentFailed(workspaceId, paymentId, 'SellerAR');
    const payment = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(payment.status).toBe('FAILED');

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.amount_due_cents).toBe(50_000);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(50_000);
  });

  test('PAY_006: reversing cleared payment reopens invoice and freezes customer', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 50_000 });

    const p = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 50_000, allocations: [{ invoice_id: invoiceId, amount_cents: 50_000 }] },
      'BuyerAP'
    );
    const paymentId = getPaymentId(p);
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const rev = await reversePayment(workspaceId, paymentId, 'SellerAdmin');
    expectSuccess(rev);
    const pay = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(pay.status).toBe('REVERSED');

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.amount_due_cents).toBe(50_000);
    expect(inv.status).not.toBe('CLOSED');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('FROZEN');
  });

  test('PAY_007: frozen customer cannot initiate payments as BuyerAP (ERR_CUSTOMER_FROZEN)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 10_000 });

    const p = await createPayment(workspaceId, customerId, { amount_cents: 10_000, allocations: [{ invoice_id: invoiceId, amount_cents: 10_000 }] }, 'BuyerAP');
    const paymentId = getPaymentId(p);
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');
    await reversePayment(workspaceId, paymentId, 'SellerAdmin').then(expectSuccess);

    const res = await postAs(`/workspaces/${workspaceId}/customers/${customerId}/payments`, { amount_cents: 10_000 }, 'BuyerAP');
    await expectErrorCode(res, 'ERR_CUSTOMER_FROZEN');
  });

  test('PAY_008: frozen customer can still record payments as SellerAR', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 10_000 });

    const p = await createPayment(workspaceId, customerId, { amount_cents: 10_000, allocations: [{ invoice_id: invoiceId, amount_cents: 10_000 }] }, 'BuyerAP');
    const paymentId = getPaymentId(p);
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');
    await reversePayment(workspaceId, paymentId, 'SellerAdmin').then(expectSuccess);

    const res = await postAs(`/workspaces/${workspaceId}/customers/${customerId}/payments`, { amount_cents: 10_000 }, 'SellerAR');
    expectSuccess(res);
  });

  test('PAY_009: explicit allocation into disputed portion fails ERR_PAYMENT_EXCEEDS_ALLOWED', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 50_000 });

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);
    await createDispute(workspaceId, invoiceId, { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_amount_cents: 20_000 }] }, 'BuyerAP');

    const before = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    const res = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/payments`,
      { amount_cents: 50_000, allocations: [{ invoice_id: invoiceId, amount_cents: 50_000 }] },
      'BuyerAP'
    );
    await expectErrorCode(res, 'ERR_PAYMENT_EXCEEDS_ALLOWED');

    const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter.amount_due_cents).toBe(50_000);
    expect(invAfter.amount_disputed_cents).toBe(20_000);
    const after = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(after.balance_due_cents).toBe(before.balance_due_cents);
    expect(after.unapplied_cash_cents).toBe(before.unapplied_cash_cents);
  });

  test('PAY_010: payment with no allocations auto-reserves only undisputed overdue payable amount', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1 });
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 50_000 });

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);
    await createDispute(workspaceId, invoiceId, { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_amount_cents: 20_000 }] }, 'BuyerAP');

    while (true) {
      const w = await getWorkspace(workspaceId, 'SellerAdmin');
      if (w.period_index >= 2) break;
      await advancePeriod(workspaceId, 'System');
    }

    const snap = await getCustomer(workspaceId, customerId, 'SellerAdmin');

    const payment = await createPayment(workspaceId, customerId, { amount_cents: 50_000 }, 'BuyerAP');
    expect(payment.status).toBe('INITIATED');
    const reserved = payment.allocations ?? payment.reserved_allocations ?? payment.reserved ?? [];
    expect(Array.isArray(reserved)).toBe(true);
    expect(reserved.length).toBeGreaterThan(0);
    expect(reserved[0].invoice_id).toBe(invoiceId);
    expect(reserved[0].amount_cents).toBe(30_000);

    const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter.amount_due_cents).toBe(50_000);
    expect(invAfter.amount_disputed_cents).toBe(20_000);

    const after = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(after.balance_due_cents).toBe(snap.balance_due_cents);
  });

  test('PAY_011: overpayment becomes unapplied_cash and invoice closes', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 50_000 });

    const p = await createPayment(workspaceId, customerId, { amount_cents: 60_000, allocations: [{ invoice_id: invoiceId, amount_cents: 50_000 }] }, 'BuyerAP');
    const paymentId = getPaymentId(p);

    const before = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('CLOSED');
    const after = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(after.unapplied_cash_cents - before.unapplied_cash_cents).toBe(10_000);
  });

  test('PAY_012: auto allocation pays oldest overdue invoice first', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1 });

    const i1 = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 30_000 });
    const inv1 = await getInvoice(workspaceId, i1, 'SellerAdmin');
    expect(inv1.due_period_index).toBe(1);

    await advancePeriod(workspaceId, 'System');

    const i2 = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 40_000 });
    const inv2 = await getInvoice(workspaceId, i2, 'SellerAdmin');
    expect(inv2.due_period_index).toBe(2);

    while (true) {
      const w = await getWorkspace(workspaceId, 'SellerAdmin');
      if (w.period_index >= 3) break;
      await advancePeriod(workspaceId, 'System');
    }

    const p = await createPayment(workspaceId, customerId, { amount_cents: 50_000 }, 'BuyerAP');
    const paymentId = getPaymentId(p);
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const i1After = await getInvoice(workspaceId, i1, 'SellerAdmin');
    expect(i1After.status).toBe('CLOSED');
    expect(i1After.amount_due_cents).toBe(0);

    const i2After = await getInvoice(workspaceId, i2, 'SellerAdmin');
    expect(i2After.amount_due_cents).toBe(20_000);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.unapplied_cash_cents).toBe(0);
  });

  test('PAY_013: BuyerAP cannot mark payments cleared (ERR_FORBIDDEN_FOR_ROLE)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 10_000 });

    const p = await createPayment(workspaceId, customerId, { amount_cents: 10_000, allocations: [{ invoice_id: invoiceId, amount_cents: 10_000 }] }, 'BuyerAP');
    const paymentId = getPaymentId(p);

    const res = await postAs(`/workspaces/${workspaceId}/payments/${paymentId}/mark_cleared`, {}, 'BuyerAP');
    await expectErrorCode(res, 'ERR_FORBIDDEN_FOR_ROLE');
  });

  test('PAY_014: cannot reverse an INITIATED payment (ERR_INVALID_STATE_TRANSITION)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 10_000 });

    const p = await createPayment(workspaceId, customerId, { amount_cents: 10_000, allocations: [{ invoice_id: invoiceId, amount_cents: 10_000 }] }, 'BuyerAP');
    const paymentId = getPaymentId(p);

    const res = await reversePayment(workspaceId, paymentId, 'SellerAdmin');
    await expectErrorCode(res, 'ERR_INVALID_STATE_TRANSITION');
  });

  test('PAY_015: early pay discount closes invoice and creates applied EARLY_PAY_DISCOUNT credit memo', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 100_000 });

    const p = await createPayment(workspaceId, customerId, { amount_cents: 98_000, allocations: [{ invoice_id: invoiceId, amount_cents: 98_000 }] }, 'BuyerAP');
    await markPaymentCleared(workspaceId, getPaymentId(p), 'SellerAR');

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('CLOSED');
    expect(inv.amount_due_cents).toBe(0);

    const cm = await findEarlyPayDiscountCreditMemo(workspaceId, customerId);
    expect(cm).toBeDefined();
    if (cm) {
      expect(cm.status).toBe('ISSUED');
    }
  });

  test('INV_202: early pay discount does not apply when short-pay exceeds 2% cap (remainder stays due)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 100_000 });

    const p = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 97_999, allocations: [{ invoice_id: invoiceId, amount_cents: 97_999 }] },
      'BuyerAP'
    );
    const paymentId = getPaymentId(p);
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const pay = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(pay.status).toBe('CLEARED');

    const cm = await findEarlyPayDiscountCreditMemo(workspaceId, customerId);
    expect(cm).toBeUndefined();

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('ACCEPTED');
    expect(inv.amount_due_cents).toBe(2_001);
    expect(inv.amount_disputed_cents).toBe(0);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(2_001);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);
  });

  test('INV_203: early pay discount does not apply when short-pay exceeds $500 max (remainder stays due)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 3_000_000 });

    const p = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 2_945_000, allocations: [{ invoice_id: invoiceId, amount_cents: 2_945_000 }] },
      'BuyerAP'
    );
    const paymentId = getPaymentId(p);
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const pay = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(pay.status).toBe('CLEARED');

    const cm = await findEarlyPayDiscountCreditMemo(workspaceId, customerId);
    expect(cm).toBeUndefined();

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('ACCEPTED');
    expect(inv.amount_due_cents).toBe(55_000);
    expect(inv.amount_disputed_cents).toBe(0);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(55_000);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);
  });

  test('PAY_016: early pay discount does not apply when paid in multiple payments', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 100_000 });

    const p1 = await createPayment(workspaceId, customerId, { amount_cents: 49_000, allocations: [{ invoice_id: invoiceId, amount_cents: 49_000 }] }, 'BuyerAP');
    await markPaymentCleared(workspaceId, getPaymentId(p1), 'SellerAR');
    const p2 = await createPayment(workspaceId, customerId, { amount_cents: 49_000, allocations: [{ invoice_id: invoiceId, amount_cents: 49_000 }] }, 'BuyerAP');
    await markPaymentCleared(workspaceId, getPaymentId(p2), 'SellerAR');

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).not.toBe('CLOSED');
    expect(inv.amount_due_cents).toBe(2_000);

    const cm = await findEarlyPayDiscountCreditMemo(workspaceId, customerId);
    expect(cm).toBeUndefined();
  });

  test('PAY_017: early pay discount does not apply when invoice has prior credits applied', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 100_000 });

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const lineId = getFirstInvoiceLineId(inv0);
    const cmManualRes = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/credit_memos`,
      { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: lineId, quantity_units: 1, unit_price_cents: 1000 }] },
      'SellerAR'
    );
    expectSuccess(cmManualRes);
    const cmManual = cmManualRes.body?.data ?? cmManualRes.body;
    const cmManualId = cmManual.credit_memo_id ?? cmManual.id;
    await postAs(`/workspaces/${workspaceId}/credit_memos/${cmManualId}/issue`, {}, 'SellerAR').then(expectSuccess);
    await postAs(`/workspaces/${workspaceId}/credit_memos/${cmManualId}/apply`, { invoice_id: invoiceId }, 'SellerAR').then(expectSuccess);

    const p = await createPayment(workspaceId, customerId, { amount_cents: 98_000, allocations: [{ invoice_id: invoiceId, amount_cents: 98_000 }] }, 'BuyerAP');
    await markPaymentCleared(workspaceId, getPaymentId(p), 'SellerAR');

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).not.toBe('CLOSED');

    expect(inv.amount_due_cents).toBe(1_000);

    const cm = await findEarlyPayDiscountCreditMemo(workspaceId, customerId);
    expect(cm).toBeUndefined();
  });

  test('PAY_018: early pay discount does not apply when invoice has active dispute', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 100_000 });

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const lineId = getFirstInvoiceLineId(inv0);
    await createDispute(workspaceId, invoiceId, { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: 1000 }] }, 'BuyerAP');

    const p = await createPayment(workspaceId, customerId, { amount_cents: 98_000, allocations: [{ invoice_id: invoiceId, amount_cents: 98_000 }] }, 'BuyerAP');
    await markPaymentCleared(workspaceId, getPaymentId(p), 'SellerAR');

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).not.toBe('CLOSED');
    expect(inv.amount_due_cents).toBe(2_000);

    const cm = await findEarlyPayDiscountCreditMemo(workspaceId, customerId);
    expect(cm).toBeUndefined();
  });

  test('PAY_019: early pay discount does not apply when invoice is past due', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 100_000 });

    while (true) {
      const w = await getWorkspace(workspaceId, 'SellerAdmin');
      if (w.period_index >= 3) break;
      await advancePeriod(workspaceId, 'System');
    }

    const p = await createPayment(workspaceId, customerId, { amount_cents: 98_000, allocations: [{ invoice_id: invoiceId, amount_cents: 98_000 }] }, 'BuyerAP');
    await markPaymentCleared(workspaceId, getPaymentId(p), 'SellerAR');

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).not.toBe('CLOSED');
    expect(inv.amount_due_cents).toBe(2_000);

    const cm = await findEarlyPayDiscountCreditMemo(workspaceId, customerId);
    expect(cm).toBeUndefined();
  });

  test('PAY_020: reversing discounted payment voids the discount credit memo and restores invoice due', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 100_000 });

    const p = await createPayment(workspaceId, customerId, { amount_cents: 98_000, allocations: [{ invoice_id: invoiceId, amount_cents: 98_000 }] }, 'BuyerAP');
    const paymentId = getPaymentId(p);
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const cm = await findEarlyPayDiscountCreditMemo(workspaceId, customerId);
    expect(cm).toBeDefined();
    const cmId = cm?.credit_memo_id ?? cm?.id;
    if (!cmId) throw new Error('Could not determine EARLY_PAY_DISCOUNT credit memo id');

    await reversePayment(workspaceId, paymentId, 'SellerAdmin').then(expectSuccess);

    const cmAfter = await getCreditMemo(workspaceId, cmId, 'SellerAdmin');
    expect(cmAfter.status).toBe('VOIDED');
    const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter.amount_due_cents).toBe(100_000);
  });

  test('PAY_021: allocations sum > amount_cents fails ERR_INVALID_REQUEST', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 10_000 });

    const res = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/payments`,
      { amount_cents: 10_000, allocations: [{ invoice_id: invoiceId, amount_cents: 12_000 }] },
      'BuyerAP'
    );
    await expectErrorCode(res, 'ERR_INVALID_REQUEST');
  });

  test('PAY_022: cannot pay a VOIDED invoice (ERR_INVOICE_NOT_PAYABLE)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/lines`, { description: 'Line', quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR').then(
      expectSuccess
    );
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/void`, {}, 'SellerAR').then(expectSuccess);

    const res = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/payments`,
      { amount_cents: 10_000, allocations: [{ invoice_id: invoiceId, amount_cents: 10_000 }] },
      'BuyerAP'
    );
    await expectErrorCode(res, 'ERR_INVOICE_NOT_PAYABLE');
  });

  test('PAY_023: cannot pay a CLOSED invoice (ERR_INVOICE_NOT_PAYABLE)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 10_000 });

    const p = await createPayment(workspaceId, customerId, { amount_cents: 10_000, allocations: [{ invoice_id: invoiceId, amount_cents: 10_000 }] }, 'BuyerAP');
    await markPaymentCleared(workspaceId, getPaymentId(p), 'SellerAR');

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('CLOSED');

    const res = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/payments`,
      { amount_cents: 10_000, allocations: [{ invoice_id: invoiceId, amount_cents: 10_000 }] },
      'BuyerAP'
    );
    await expectErrorCode(res, 'ERR_INVOICE_NOT_PAYABLE');
  });

  test('PAY_024: clearing payment with dispute allocates only undisputed; remainder becomes unapplied cash', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 50_000 });

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const lineId = getFirstInvoiceLineId(inv0);
    await createDispute(workspaceId, invoiceId, { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: 20_000 }] }, 'BuyerAP');

    const before = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    const p = await createPayment(workspaceId, customerId, { amount_cents: 50_000 }, 'BuyerAP');
    await markPaymentCleared(workspaceId, getPaymentId(p), 'SellerAR');
    const after = await getCustomer(workspaceId, customerId, 'SellerAdmin');

    expect(before.balance_due_cents - after.balance_due_cents).toBe(30_000);
    expect(after.unapplied_cash_cents - before.unapplied_cash_cents).toBe(20_000);
  });

  test('PAY_025: clearing initiated payment applies only amount still payable; remainder becomes unapplied cash', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 50_000 });

    const p = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 50_000, allocations: [{ invoice_id: invoiceId, amount_cents: 50_000 }] },
      'BuyerAP'
    );
    const paymentId = getPaymentId(p);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const lineId = getFirstInvoiceLineId(inv0);
    await createDispute(workspaceId, invoiceId, { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: 10_000 }] }, 'BuyerAP');

    const before = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');
    const after = await getCustomer(workspaceId, customerId, 'SellerAdmin');

    const inv1 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv1.amount_due_cents).toBe(10_000);
    expect(after.unapplied_cash_cents - before.unapplied_cash_cents).toBe(10_000);
  });

  test('PAY_026: clearing payment with no allocations auto-allocates to oldest overdue invoice', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1 });
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 50_000 });

    while (true) {
      const w = await getWorkspace(workspaceId, 'SellerAdmin');
      if (w.period_index >= 2) break;
      await advancePeriod(workspaceId, 'System');
    }

    const beforeCust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    const beforeInv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');

    const p = await createPayment(workspaceId, customerId, { amount_cents: 10_000 }, 'BuyerAP');
    await markPaymentCleared(workspaceId, getPaymentId(p), 'SellerAR');

    const afterInv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(beforeInv.amount_due_cents - afterInv.amount_due_cents).toBe(10_000);

    const afterCust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(beforeCust.balance_due_cents - afterCust.balance_due_cents).toBe(10_000);
    expect(afterCust.unapplied_cash_cents).toBe(beforeCust.unapplied_cash_cents);
  });

  test('PAY_027: auto allocation skips fully disputed invoice and pays undisputed invoice first', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1 });

    const i1 = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 10_000 });
    const i2 = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 10_000 });

    while (true) {
      const w = await getWorkspace(workspaceId, 'SellerAdmin');
      if (w.period_index >= 2) break;
      await advancePeriod(workspaceId, 'System');
    }

    const inv1 = await getInvoice(workspaceId, i1, 'SellerAdmin');
    const lineId = getFirstInvoiceLineId(inv1);
    await createDispute(workspaceId, i1, { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: 10_000 }] }, 'BuyerAP');

    const p = await createPayment(workspaceId, customerId, { amount_cents: 10_000 }, 'BuyerAP');
    await markPaymentCleared(workspaceId, getPaymentId(p), 'SellerAR');

    const i2After = await getInvoice(workspaceId, i2, 'SellerAdmin');
    expect(i2After.status).toBe('CLOSED');

    const i1After = await getInvoice(workspaceId, i1, 'SellerAdmin');
    expect(i1After.amount_due_cents).toBe(10_000);
  });

  test('PAY_028: write_off is blocked for already CLOSED invoice (ERR_WRITE_OFF_NOT_ALLOWED)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 10_000 });

    const p = await createPayment(workspaceId, customerId, { amount_cents: 10_000, allocations: [{ invoice_id: invoiceId, amount_cents: 10_000 }] }, 'BuyerAP');
    await markPaymentCleared(workspaceId, getPaymentId(p), 'SellerAR');
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('CLOSED');

    const res = await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/write_off`, {}, 'SellerAR');
    await expectErrorCode(res, 'ERR_WRITE_OFF_NOT_ALLOWED');
  });

  test('PAY_029: cannot reverse a FAILED payment (ERR_INVALID_STATE_TRANSITION)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 10_000 });

    const p = await createPayment(workspaceId, customerId, { amount_cents: 10_000, allocations: [{ invoice_id: invoiceId, amount_cents: 10_000 }] }, 'BuyerAP');
    const paymentId = getPaymentId(p);
    await markPaymentFailed(workspaceId, paymentId, 'SellerAR');

    const res = await reversePayment(workspaceId, paymentId, 'SellerAdmin');
    await expectErrorCode(res, 'ERR_INVALID_STATE_TRANSITION');
  });

  test('PAY_030: reversal is allowed even after books are closed through payment period', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 10_000 });

    const p = await createPayment(workspaceId, customerId, { amount_cents: 10_000, allocations: [{ invoice_id: invoiceId, amount_cents: 10_000 }] }, 'BuyerAP');
    const paymentId = getPaymentId(p);
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    await advancePeriod(workspaceId, 'System');
    await closeBooks(workspaceId, 'Auditor').then(expectSuccess);

    const res = await reversePayment(workspaceId, paymentId, 'SellerAdmin');
    expectSuccess(res);

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.amount_due_cents).toBe(10_000);
    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('FROZEN');
  });

  test('PAY_031: auto-allocation tie-breaker uses (due_period_index, invoice_id)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1 });

    const i1 = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 30_000 });
    const i2 = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 30_000 });
    const [minId, maxId] = [i1, i2].sort();

    while (true) {
      const w = await getWorkspace(workspaceId, 'SellerAdmin');
      if (w.period_index >= 2) break;
      await advancePeriod(workspaceId, 'System');
    }

    const p = await createPayment(workspaceId, customerId, { amount_cents: 30_000 }, 'BuyerAP');
    await markPaymentCleared(workspaceId, getPaymentId(p), 'SellerAR');

    const invMin = await getInvoice(workspaceId, minId, 'SellerAdmin');
    const invMax = await getInvoice(workspaceId, maxId, 'SellerAdmin');
    expect(invMin.status).toBe('CLOSED');
    expect(invMin.amount_due_cents).toBe(0);
    expect(invMax.amount_due_cents).toBe(30_000);
    expect(invMax.status).not.toBe('CLOSED');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(30_000);
    expect(cust.unapplied_cash_cents).toBe(0);
  });

  test('DEEP_011: clearing initiated payment after credits reduces payable; remainder becomes unapplied cash', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 50_000 });

    const p = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 50_000, allocations: [{ invoice_id: invoiceId, amount_cents: 50_000 }] },
      'BuyerAP'
    );
    const paymentId = getPaymentId(p);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const lineId = getFirstInvoiceLineId(inv0);
    const cm = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/credit_memos`,
      { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: lineId, quantity_units: 2, unit_price_cents: 10_000 }] },
      'SellerAR'
    );
    expectSuccess(cm);
    const cmBody = cm.body?.data ?? cm.body;
    const cmId = cmBody.credit_memo_id ?? cmBody.id;
    if (!cmId) throw new Error('Could not resolve credit memo id');
    await postAs(`/workspaces/${workspaceId}/credit_memos/${cmId}/issue`, {}, 'SellerAR').then(expectSuccess);
    await postAs(`/workspaces/${workspaceId}/credit_memos/${cmId}/apply`, { invoice_id: invoiceId }, 'SellerAR').then(expectSuccess);

    const before = await getCustomer(workspaceId, customerId, 'SellerAdmin');

    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const pay = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(pay.status).toBe('CLEARED');

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.amount_due_cents).toBe(0);
    expect(inv.status).toBe('CLOSED');

    const after = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(before.balance_due_cents - after.balance_due_cents).toBe(30_000);
    expect(after.unapplied_cash_cents - before.unapplied_cash_cents).toBe(20_000);
    expect(after.available_credit_cents).toBe(before.available_credit_cents);
  });

  test('TRANS_001: early pay discount does not apply if a prior credit is applied before clearing an initiated short-pay', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 100_000 });

    const initiated = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 98_000, allocations: [{ invoice_id: invoiceId, amount_cents: 98_000 }] },
      'BuyerAP'
    );
    const paymentId = getPaymentId(initiated);
    expect(initiated.status).toBe('INITIATED');

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const lineId = getFirstInvoiceLineId(inv0);
    const cmRes = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/credit_memos`,
      { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: lineId, quantity_units: 1, unit_price_cents: 1_000 }] },
      'SellerAR'
    );
    expectSuccess(cmRes);
    const cmBody = cmRes.body?.data ?? cmRes.body;
    const cmId = cmBody.credit_memo_id ?? cmBody.id;
    if (!cmId) throw new Error('Could not resolve credit memo id');
    await postAs(`/workspaces/${workspaceId}/credit_memos/${cmId}/issue`, {}, 'SellerAR').then(expectSuccess);
    await postAs(`/workspaces/${workspaceId}/credit_memos/${cmId}/apply`, { invoice_id: invoiceId }, 'SellerAR').then(expectSuccess);

    const beforeClear = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    const epdBefore = await findEarlyPayDiscountCreditMemo(workspaceId, customerId);
    expect(epdBefore).toBeUndefined();

    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const epdAfter = await findEarlyPayDiscountCreditMemo(workspaceId, customerId);
    expect(epdAfter).toBeUndefined();

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).not.toBe('CLOSED');
    expect(inv.amount_due_cents).toBe(1_000);
    expect(inv.amount_disputed_cents).toBe(0);

    const afterClear = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(afterClear.unapplied_cash_cents).toBe(beforeClear.unapplied_cash_cents);
    expect(afterClear.balance_due_cents).toBe(1_000);
  });

  test('TRANS_004: clearing a reserved auto-allocation that became fully disputed does not reallocate; remainder becomes unapplied cash', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1 });

    const i1 = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 50_000 });
    const i2 = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 50_000 });
    const [iMin, iMax] = [i1, i2].sort();

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const p = await createPayment(workspaceId, customerId, { amount_cents: 50_000 }, 'BuyerAP');
    const paymentId = getPaymentId(p);
    expect(p.status).toBe('INITIATED');
    const reserved = (p.allocations ?? p.reserved_allocations ?? p.reserved ?? []) as any[];
    expect(reserved).toHaveLength(1);
    expect(reserved[0].invoice_id).toBe(iMin);
    expect(reserved[0].amount_cents).toBe(50_000);

    const invMin0 = await getInvoice(workspaceId, iMin, 'SellerAdmin');
    const lineId = getFirstInvoiceLineId(invMin0);
    await createDispute(
      workspaceId,
      iMin,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: 50_000 }] },
      'BuyerAP'
    );

    const before = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    const balanceBefore = before.balance_due_cents as number;
    const unappliedBefore = before.unapplied_cash_cents as number;

    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const pay = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(pay.status).toBe('CLEARED');

    const invMin1 = await getInvoice(workspaceId, iMin, 'SellerAdmin');
    expect(invMin1.status).toBe('ACCEPTED');
    expect(invMin1.amount_due_cents).toBe(50_000);
    expect(invMin1.amount_disputed_cents).toBe(50_000);

    const invMax1 = await getInvoice(workspaceId, iMax, 'SellerAdmin');
    expect(invMax1.status).toBe('ACCEPTED');
    expect(invMax1.amount_due_cents).toBe(50_000);

    const after = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(after.balance_due_cents).toBe(balanceBefore);
    expect(after.unapplied_cash_cents).toBe(unappliedBefore + 50_000);
  });

  test('REV_001: reversal voids early-pay discount but preserves unrelated available credits', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 100_000 });

    const discounted = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 98_000, allocations: [{ invoice_id: invoiceId, amount_cents: 98_000 }] },
      'BuyerAP'
    );
    const paymentId = getPaymentId(discounted);
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const epd = await findEarlyPayDiscountCreditMemo(workspaceId, customerId);
    expect(epd).toBeDefined();
    const epdId = epd?.credit_memo_id ?? epd?.id;
    if (!epdId) throw new Error('Could not resolve EARLY_PAY_DISCOUNT credit memo id');

    const gwRes = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/credit_memos`,
      { reason: 'GOODWILL', items: [{ quantity_units: 1, unit_price_cents: 5_000 }] },
      'SellerAR'
    );
    expectSuccess(gwRes);
    const gwBody = gwRes.body?.data ?? gwRes.body;
    const gwId = gwBody.credit_memo_id ?? gwBody.id;
    if (!gwId) throw new Error('Could not resolve goodwill credit memo id');
    await postAs(`/workspaces/${workspaceId}/credit_memos/${gwId}/issue`, {}, 'SellerAR').then(expectSuccess);

    const snap = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(snap.available_credit_cents).toBe(5_000);
    expect(snap.unapplied_cash_cents).toBe(0);

    await reversePayment(workspaceId, paymentId, 'SellerAdmin').then(expectSuccess);

    const pay = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(pay.status).toBe('REVERSED');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('FROZEN');
    expect(cust.available_credit_cents).toBe(5_000);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.balance_due_cents).toBe(100_000);

    const epdAfter = await getCreditMemo(workspaceId, epdId, 'SellerAdmin');
    expect(epdAfter.status).toBe('VOIDED');

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('ACCEPTED');
    expect(inv.amount_due_cents).toBe(100_000);
    expect(inv.amount_disputed_cents).toBe(0);
  });

  test('REV_002: reversal undoes unapplied cash created by that payment, but preserves unapplied cash from later payments', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 40_000 });

    const p1 = await createPayment(workspaceId, customerId, { amount_cents: 60_000 }, 'BuyerAP');
    const p1Id = getPaymentId(p1);
    await markPaymentCleared(workspaceId, p1Id, 'SellerAR');

    const invClosed = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invClosed.status).toBe('CLOSED');

    const p2 = await createPayment(workspaceId, customerId, { amount_cents: 10_000 }, 'BuyerAP');
    const p2Id = getPaymentId(p2);
    await markPaymentCleared(workspaceId, p2Id, 'SellerAR');

    const snap = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(snap.unapplied_cash_cents).toBe(30_000);

    await reversePayment(workspaceId, p1Id, 'SellerAdmin').then(expectSuccess);

    const pay1 = await getPayment(workspaceId, p1Id, 'SellerAdmin');
    expect(pay1.status).toBe('REVERSED');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('FROZEN');
    expect(cust.unapplied_cash_cents).toBe(10_000);
    expect(cust.balance_due_cents).toBe(40_000);

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('ACCEPTED');
    expect(inv.amount_due_cents).toBe(40_000);
  });

  test('REV_003: reversal preserves applied (non-discount) credits; invoice reopens to net-of-credit amount due', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });

    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 50_000 });
    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const lineId = getFirstInvoiceLineId(inv0);

    const cmRes = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/credit_memos`,
      { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: lineId, quantity_units: 2, unit_price_cents: 10_000 }] },
      'SellerAR'
    );
    expectSuccess(cmRes);
    const cmBody = cmRes.body?.data ?? cmRes.body;
    const cmId = cmBody.credit_memo_id ?? cmBody.id;
    if (!cmId) throw new Error('Could not resolve credit memo id');
    await postAs(`/workspaces/${workspaceId}/credit_memos/${cmId}/issue`, {}, 'SellerAR').then(expectSuccess);
    await postAs(`/workspaces/${workspaceId}/credit_memos/${cmId}/apply`, { invoice_id: invoiceId }, 'SellerAR').then(expectSuccess);

    const invAfterCredit = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfterCredit.amount_due_cents).toBe(30_000);

    const p = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 30_000, allocations: [{ invoice_id: invoiceId, amount_cents: 30_000 }] },
      'BuyerAP'
    );
    const paymentId = getPaymentId(p);
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const invClosed = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invClosed.status).toBe('CLOSED');
    const custClosed = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custClosed.balance_due_cents).toBe(0);
    expect(custClosed.available_credit_cents).toBe(0);
    expect(custClosed.unapplied_cash_cents).toBe(0);

    await reversePayment(workspaceId, paymentId, 'SellerAdmin').then(expectSuccess);

    const pay = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(pay.status).toBe('REVERSED');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('FROZEN');
    expect(cust.available_credit_cents).toBe(0);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.balance_due_cents).toBe(30_000);

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('ACCEPTED');
    expect(inv.amount_due_cents).toBe(30_000);
    expect(inv.amount_disputed_cents).toBe(0);

    const cm = await getCreditMemo(workspaceId, cmId, 'SellerAdmin');
    expect(cm.status).toBe('ISSUED');

    const all = (await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin')) as any[];
    const sumDue = all
      .filter((i: any) => i.status !== 'VOIDED')
      .reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
    expect(sumDue).toBe(30_000);
  });

  test('TRANS_005: auto-allocation pays earliest-due invoice even before it is overdue', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1 });

    const i1 = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 20_000 });
    const inv1 = await getInvoice(workspaceId, i1, 'SellerAdmin');
    expect(inv1.accepted_period_index).toBe(0);
    expect(inv1.due_period_index).toBe(1);

    await advancePeriod(workspaceId, 'System');

    const i2 = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 20_000 });
    const inv2 = await getInvoice(workspaceId, i2, 'SellerAdmin');
    expect(inv2.accepted_period_index).toBe(1);
    expect(inv2.due_period_index).toBe(2);

    const p = await createPayment(workspaceId, customerId, { amount_cents: 20_000 }, 'BuyerAP');
    const paymentId = getPaymentId(p);
    expect(p.status).toBe('INITIATED');

    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');
    const pay = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(pay.status).toBe('CLEARED');

    const i1After = await getInvoice(workspaceId, i1, 'SellerAdmin');
    const i2After = await getInvoice(workspaceId, i2, 'SellerAdmin');
    expect(i1After.status).toBe('CLOSED');
    expect(i1After.amount_due_cents).toBe(0);
    expect(i2After.status).toBe('ACCEPTED');
    expect(i2After.amount_due_cents).toBe(20_000);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(20_000);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);

    expect((i1After.amount_due_cents as number) + (i2After.amount_due_cents as number)).toBe(cust.balance_due_cents);
  });

  test('TRANS_007: early-pay discount does not apply if payment clears more than one period after acceptance', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 3 });
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 100_000 });

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const initiated = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 98_000, allocations: [{ invoice_id: invoiceId, amount_cents: 98_000 }] },
      'BuyerAP'
    );
    const paymentId = getPaymentId(initiated);
    expect(initiated.status).toBe('INITIATED');

    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const list = await listCreditMemos(workspaceId, { customer_id: customerId, status: 'ISSUED' }, 'SellerAdmin');
    const hasEPD = (list as any[]).some((cm: any) => (cm?.type ?? cm?.credit_memo_type ?? cm?.reason) === 'EARLY_PAY_DISCOUNT');
    expect(hasEPD).toBe(false);

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('ACCEPTED');
    expect(inv.amount_due_cents).toBe(2_000);
    expect(inv.amount_disputed_cents).toBe(0);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(2_000);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);

    const ws = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(ws.period_index).toBe(2);
    expect(inv.due_period_index).toBe(3);
  });

  test('TRANS_008: accepting a fully credited CLOSED invoice fails ERR_INVALID_STATE_TRANSITION and does not set acceptance fields', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `T8-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/lines`, { description: 'Line', quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR').then(
      expectSuccess
    );
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.status).toBe('SENT');
    const lineId = getFirstInvoiceLineId(inv0);

    const cmRes = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/credit_memos`,
      { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: lineId, quantity_units: 1, unit_price_cents: 10_000 }] },
      'SellerAR'
    );
    expectSuccess(cmRes);
    const cmBody = cmRes.body?.data ?? cmRes.body;
    const cmId = cmBody.credit_memo_id ?? cmBody.id;
    if (!cmId) throw new Error('Could not resolve credit memo id');
    await postAs(`/workspaces/${workspaceId}/credit_memos/${cmId}/issue`, {}, 'SellerAR').then(expectSuccess);
    await postAs(`/workspaces/${workspaceId}/credit_memos/${cmId}/apply`, { invoice_id: invoiceId }, 'SellerAR').then(expectSuccess);

    const closed = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(closed.status).toBe('CLOSED');
    expect(closed.amount_due_cents).toBe(0);
    expect(closed.accepted_period_index == null).toBe(true);
    expect(closed.due_period_index == null).toBe(true);

    const res = await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/accept`, {}, 'BuyerAP');
    await expectErrorCode(res, 'ERR_INVALID_STATE_TRANSITION');

    const stillClosed = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(stillClosed.status).toBe('CLOSED');
    expect(stillClosed.amount_due_cents).toBe(0);
    expect(stillClosed.accepted_period_index == null).toBe(true);
    expect(stillClosed.due_period_index == null).toBe(true);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(0);
  });

  test('TRANS_009: billing cap is enforced per (customer, contract, period) not across contracts', async () => {
    const ws = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
    const workspaceId = ws.workspace_id;
    const customer = await createCustomer(workspaceId, {}, 'SellerAdmin');
    const customerId = getCustomerId(customer);

    const k1 = await createContract(workspaceId, customerId, { name: `K1-${uniqueId('k')}`, requires_po: false, billing_cap_cents_per_period: 10_000_000 }, 'SellerAdmin');
    const k2 = await createContract(workspaceId, customerId, { name: `K2-${uniqueId('k')}`, requires_po: false, billing_cap_cents_per_period: 10_000_000 }, 'SellerAdmin');
    const k1Id = getContractId(k1);
    const k2Id = getContractId(k2);
    await activateContract(workspaceId, k1Id, 'SellerAdmin');
    await activateContract(workspaceId, k2Id, 'SellerAdmin');

    const i1 = await createInvoice(workspaceId, customerId, { contract_id: k1Id, external_invoice_ref: `T9-I1-${uniqueId('inv')}` }, 'SellerAR');
    const i2 = await createInvoice(workspaceId, customerId, { contract_id: k2Id, external_invoice_ref: `T9-I2-${uniqueId('inv')}` }, 'SellerAR');
    const i1Id = getInvoiceId(i1);
    const i2Id = getInvoiceId(i2);

    await postAs(`/workspaces/${workspaceId}/invoices/${i1Id}/lines`, { description: 'I1', quantity_units: 900, unit_price_cents: 10_000 }, 'SellerAR').then(expectSuccess);
    await postAs(`/workspaces/${workspaceId}/invoices/${i2Id}/lines`, { description: 'I2', quantity_units: 900, unit_price_cents: 10_000 }, 'SellerAR').then(expectSuccess);
    await finalizeInvoice(workspaceId, i1Id, {}, 'SellerAR');
    await finalizeInvoice(workspaceId, i2Id, {}, 'SellerAR');

    const i3 = await createInvoice(workspaceId, customerId, { contract_id: k1Id, external_invoice_ref: `T9-I3-${uniqueId('inv')}` }, 'SellerAR');
    const i3Id = getInvoiceId(i3);
    await postAs(`/workspaces/${workspaceId}/invoices/${i3Id}/lines`, { description: 'I3', quantity_units: 200, unit_price_cents: 10_000 }, 'SellerAR').then(expectSuccess);

    const snap = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(snap.balance_due_cents).toBe(18_000_000);

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${i3Id}/finalize`,
      { override_hold: false, override_billing_cap: false, final_invoice: false },
      'SellerAR'
    );
    await expectErrorCode(res, 'ERR_BILLING_CAP_EXCEEDED');

    const inv3 = await getInvoice(workspaceId, i3Id, 'SellerAdmin');
    expect(inv3.status).toBe('DRAFT');
    expect(inv3.invoice_total_cents).toBe(0);

    const inv1 = await getInvoice(workspaceId, i1Id, 'SellerAdmin');
    const inv2 = await getInvoice(workspaceId, i2Id, 'SellerAdmin');
    expect(inv1.status).toBe('FINALIZED');
    expect(inv2.status).toBe('FINALIZED');
    expect(inv1.issued_period_index).toBe(0);
    expect(inv2.issued_period_index).toBe(0);
    expect(inv1.invoice_total_cents).toBe(9_000_000);
    expect(inv2.invoice_total_cents).toBe(9_000_000);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(18_000_000);
  });

  test('TRANS_010: early-pay discount eligibility uses accepted_period_index even when acceptance was deemed', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 10, unit_price_cents: 10_000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId, external_invoice_ref: `T10-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/lines`,
      { description: 'Line', quantity_units: 10, unit_price_cents: 10_000, purchase_order_line_id: poLineId },
      'SellerAR'
    ).then(expectSuccess);
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const invAccepted = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAccepted.status).toBe('ACCEPTED');
    expect(invAccepted.accepted_period_index).toBe(1);
    expect(invAccepted.due_period_index).toBe(3);

    const p = await createPayment(workspaceId, customerId, { amount_cents: 98_000, allocations: [{ invoice_id: invoiceId, amount_cents: 98_000 }] }, 'BuyerAP');
    const paymentId = getPaymentId(p);
    const ws = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(ws.period_index).toBe(2);
    expect(ws.period_index).toBeLessThanOrEqual(invAccepted.due_period_index);

    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('CLOSED');
    expect(inv.amount_due_cents).toBe(0);
    expect(inv.accepted_period_index).toBe(1);
    expect(inv.due_period_index).toBe(3);

    const epd = (await listCreditMemos(workspaceId, { customer_id: customerId }, 'SellerAdmin')).find(
      (cm: any) => (cm?.type ?? cm?.credit_memo_type ?? cm?.reason) === 'EARLY_PAY_DISCOUNT'
    );
    expect(epd).toBeDefined();
    const epdId = epd?.credit_memo_id ?? epd?.id;
    if (!epdId) throw new Error('Could not resolve EARLY_PAY_DISCOUNT credit memo id');

    const epdFull = await getCreditMemo(workspaceId, epdId, 'SellerAdmin');
    const total =
      (typeof epdFull?.credit_total_cents === 'number' ? epdFull.credit_total_cents : undefined) ??
      (typeof epdFull?.amount_cents === 'number' ? epdFull.amount_cents : undefined) ??
      (Array.isArray(epdFull?.items)
        ? (epdFull.items as any[]).reduce((s, it) => {
            const amt =
              (typeof it?.amount_cents === 'number' ? it.amount_cents : undefined) ??
              (typeof it?.quantity_units === 'number' && typeof it?.unit_price_cents === 'number' ? it.quantity_units * it.unit_price_cents : 0);
            return s + Number(amt ?? 0);
          }, 0)
        : undefined);
    expect(total).toBe(2_000);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);
    expect(cust.unapplied_cash_cents).toBe(0);
  });

  test('TRANS_013: early pay discount still applies when a manual credit memo is ISSUED but not applied', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 100_000 });

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const lineId = getFirstInvoiceLineId(inv0);

    const cmRes = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/credit_memos`,
      { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: lineId, quantity_units: 1, unit_price_cents: 1_000 }] },
      'SellerAR'
    );
    expectSuccess(cmRes);
    const cmBody = cmRes.body?.data ?? cmRes.body;
    const cmId = cmBody.credit_memo_id ?? cmBody.id;
    if (!cmId) throw new Error('Could not resolve manual credit memo id');
    await postAs(`/workspaces/${workspaceId}/credit_memos/${cmId}/issue`, {}, 'SellerAR').then(expectSuccess);

    const invPrePay = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invPrePay.amount_due_cents).toBe(100_000);
    const custPrePay = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custPrePay.available_credit_cents).toBe(1_000);

    const p = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 98_000, allocations: [{ invoice_id: invoiceId, amount_cents: 98_000 }] },
      'BuyerAP'
    );
    const paymentId = getPaymentId(p);
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const pay = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(pay.status).toBe('CLEARED');

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('CLOSED');
    expect(inv.amount_due_cents).toBe(0);
    expect(inv.amount_disputed_cents).toBe(0);
    expect(inv.accepted_period_index).toBe(0);
    expect(inv.due_period_index).toBe(2);

    const epd = await findEarlyPayDiscountCreditMemo(workspaceId, customerId);
    expect(epd).toBeDefined();
    if (epd) expect(epd.status).toBe('ISSUED');

    const cm = await getCreditMemo(workspaceId, cmId, 'SellerAdmin');
    expect(cm.status).toBe('ISSUED');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(0);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(1_000);

    const all = (await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin')) as any[];
    const sumDue = all
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
    expect(sumDue).toBe(0);
    expect(sumDue).toBe(cust.balance_due_cents);
  });

  test('TRANS_016: clearing a no-allocation payment created before any invoices does not retroactively allocate to later invoices', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });

    const p = await createPayment(workspaceId, customerId, { amount_cents: 10_000 }, 'BuyerAP');
    const paymentId = getPaymentId(p);

    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 10_000 });

    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const pay = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(pay.status).toBe('CLEARED');

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('ACCEPTED');
    expect(inv.amount_due_cents).toBe(10_000);
    expect(inv.amount_disputed_cents).toBe(0);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(10_000);
    expect(cust.unapplied_cash_cents).toBe(10_000);
    expect(cust.available_credit_cents).toBe(0);

    const all = (await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin')) as any[];
    const sumDue = all
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
    expect(sumDue).toBe(10_000);
    expect(sumDue).toBe(cust.balance_due_cents);
  });

  test('REV_004: reversal restores invoice lifecycle state for a SENT (never accepted) invoice', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `R4-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/lines`, { description: 'Line', quantity_units: 5, unit_price_cents: 10_000 }, 'SellerAR').then(expectSuccess);
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');

    const sent = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(sent.status).toBe('SENT');
    expect(sent.delivered_period_index).toBe(0);
    expect(sent.accepted_period_index == null).toBe(true);
    expect(sent.due_period_index == null).toBe(true);

    const payment = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 50_000, allocations: [{ invoice_id: invoiceId, amount_cents: 50_000 }] },
      'BuyerAP'
    );
    const paymentId = getPaymentId(payment);
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const closed = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(closed.status).toBe('CLOSED');
    expect(closed.amount_due_cents).toBe(0);
    const cust0 = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust0.balance_due_cents).toBe(0);

    await reversePayment(workspaceId, paymentId, 'SellerAdmin').then(expectSuccess);

    const pay = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(pay.status).toBe('REVERSED');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('FROZEN');
    expect(cust.balance_due_cents).toBe(50_000);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('SENT');
    expect(inv.amount_due_cents).toBe(50_000);
    expect(inv.delivered_period_index).toBe(0);
    expect(inv.accepted_period_index == null).toBe(true);
    expect(inv.due_period_index == null).toBe(true);

    const all = (await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin')) as any[];
    const sumDue = all.filter((i: any) => i.status !== 'VOIDED').reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
    expect(sumDue).toBe(50_000);
    expect(sumDue).toBe(cust.balance_due_cents);
  });

  test('REV_005: reversal after write_off restores payment portion but preserves write-off (and collections stage)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1 });
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 15_000 });

    while (true) {
      const ws = await getWorkspace(workspaceId, 'SellerAdmin');
      if (ws.period_index >= 4) break;
      await advancePeriod(workspaceId, 'System');
    }

    const invColl = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invColl.collections_stage).toBe('COLLECTIONS');

    const p = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 10_000, allocations: [{ invoice_id: invoiceId, amount_cents: 10_000 }] },
      'BuyerAP'
    );
    const paymentId = getPaymentId(p);
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const invAfterPay = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfterPay.amount_due_cents).toBe(5_000);

    const wo = await writeOffInvoice(workspaceId, invoiceId, 'SellerAR');
    expectSuccess(wo);
    const invClosed = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invClosed.status).toBe('CLOSED');
    expect(invClosed.amount_due_cents).toBe(0);

    await reversePayment(workspaceId, paymentId, 'SellerAdmin').then(expectSuccess);

    const pay = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(pay.status).toBe('REVERSED');

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('ACCEPTED');
    expect(inv.amount_due_cents).toBe(10_000);
    expect(inv.amount_disputed_cents).toBe(0);
    expect(inv.collections_stage).toBe('COLLECTIONS');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('FROZEN');

    expect(cust.balance_due_cents).toBe(15_000);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);

    const all = (await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin')) as any[];
    const sumDue = all.filter((i: any) => i.status !== 'VOIDED').reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
    expect(sumDue).toBe(15_000);
    expect(sumDue).toBe(cust.balance_due_cents);
  });

  test('REV_006: reversal allowed after close_books and still voids EARLY_PAY_DISCOUNT credit memo', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 100_000 });

    const p = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 98_000, allocations: [{ invoice_id: invoiceId, amount_cents: 98_000 }] },
      'BuyerAP'
    );
    const paymentId = getPaymentId(p);
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const epd = await findEarlyPayDiscountCreditMemo(workspaceId, customerId);
    expect(epd).toBeDefined();
    const epdId = epd?.credit_memo_id ?? epd?.id;
    if (!epdId) throw new Error('Could not resolve EARLY_PAY_DISCOUNT credit memo id');

    const invClosed = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invClosed.status).toBe('CLOSED');
    expect(invClosed.amount_due_cents).toBe(0);

    await advancePeriod(workspaceId, 'System');
    await closeBooks(workspaceId, 'Auditor').then(expectSuccess);
    const ws = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(ws.period_index).toBe(1);
    expect(ws.books_closed_through_period_index).toBe(0);

    await reversePayment(workspaceId, paymentId, 'SellerAdmin').then(expectSuccess);

    const pay = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(pay.status).toBe('REVERSED');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('FROZEN');
    expect(cust.balance_due_cents).toBe(100_000);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('ACCEPTED');
    expect(inv.amount_due_cents).toBe(100_000);
    expect(inv.amount_disputed_cents).toBe(0);
    expect(inv.accepted_period_index).toBe(0);
    expect(inv.due_period_index).toBe(2);

    const epdAfter = await getCreditMemo(workspaceId, epdId, 'SellerAdmin');
    expect(epdAfter.status).toBe('VOIDED');

    const wsAfter = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(wsAfter.books_closed_through_period_index).toBe(0);

    const all = (await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin')) as any[];
    const sumDue = all
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
    expect(sumDue).toBe(100_000);
    expect(sumDue).toBe(cust.balance_due_cents);
  });

  test('REV_007: reversal restores amount_due but preserves active dispute amount_disputed', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 100_000 });

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const lineId = getFirstInvoiceLineId(inv0);

    const dispute = await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: 30_000 }] },
      'BuyerAP'
    );
    const disputeId = getDisputeId(dispute);

    const invDisputed = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invDisputed.amount_disputed_cents).toBe(30_000);

    const p = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 70_000, allocations: [{ invoice_id: invoiceId, amount_cents: 70_000 }] },
      'BuyerAP'
    );
    const paymentId = getPaymentId(p);
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const invAfterPay = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfterPay.status).toBe('ACCEPTED');
    expect(invAfterPay.amount_due_cents).toBe(30_000);
    expect(invAfterPay.amount_disputed_cents).toBe(30_000);

    await reversePayment(workspaceId, paymentId, 'SellerAdmin').then(expectSuccess);

    const pay = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(pay.status).toBe('REVERSED');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('FROZEN');
    expect(cust.balance_due_cents).toBe(100_000);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);

    const d = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(d.status).toBe('OPEN');

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('ACCEPTED');
    expect(inv.amount_due_cents).toBe(100_000);
    expect(inv.amount_disputed_cents).toBe(30_000);
    expect(inv.amount_disputed_cents).toBeGreaterThanOrEqual(0);
    expect(inv.amount_disputed_cents).toBeLessThanOrEqual(inv.amount_due_cents);
    expect((inv.amount_due_cents as number) - (inv.amount_disputed_cents as number)).toBe(70_000);
  });

  test('REV_008: reversal removes unapplied cash created by an overpayment and reopens fully paid invoices', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });

    const i1 = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 30_000 });
    const i2 = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 40_000 });

    const snap = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(snap.balance_due_cents).toBe(70_000);

    const p = await createPayment(
      workspaceId,
      customerId,
      {
        amount_cents: 80_000,
        allocations: [
          { invoice_id: i1, amount_cents: 30_000 },
          { invoice_id: i2, amount_cents: 40_000 }
        ]
      },
      'BuyerAP'
    );
    const paymentId = getPaymentId(p);
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const i1Closed = await getInvoice(workspaceId, i1, 'SellerAdmin');
    const i2Closed = await getInvoice(workspaceId, i2, 'SellerAdmin');
    expect(i1Closed.status).toBe('CLOSED');
    expect(i2Closed.status).toBe('CLOSED');

    const custCleared = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custCleared.balance_due_cents).toBe(0);
    expect(custCleared.unapplied_cash_cents).toBe(10_000);
    expect(custCleared.available_credit_cents).toBe(0);

    await reversePayment(workspaceId, paymentId, 'SellerAdmin').then(expectSuccess);

    const pay = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(pay.status).toBe('REVERSED');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('FROZEN');
    expect(cust.balance_due_cents).toBe(70_000);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);

    const i1After = await getInvoice(workspaceId, i1, 'SellerAdmin');
    const i2After = await getInvoice(workspaceId, i2, 'SellerAdmin');
    expect(i1After.status).toBe('ACCEPTED');
    expect(i1After.amount_due_cents).toBe(30_000);
    expect(i2After.status).toBe('ACCEPTED');
    expect(i2After.amount_due_cents).toBe(40_000);

    const all = (await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin')) as any[];
    const sumDue = all
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
    expect(sumDue).toBe(70_000);
    expect(sumDue).toBe(cust.balance_due_cents);
  });

  test('REV_009: reversing a cash-only payment removes unapplied cash but does not affect later invoices', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });

    const p = await createPayment(workspaceId, customerId, { amount_cents: 10_000 }, 'BuyerAP');
    const paymentId = getPaymentId(p);
    expect(p.status).toBe('INITIATED');

    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const afterClear = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(afterClear.unapplied_cash_cents).toBe(10_000);
    expect(afterClear.balance_due_cents).toBe(0);
    expect(afterClear.available_credit_cents).toBe(0);

    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 10_000 });

    const pre = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(pre.balance_due_cents).toBe(10_000);
    expect(pre.unapplied_cash_cents).toBe(10_000);
    expect(pre.available_credit_cents).toBe(0);

    await reversePayment(workspaceId, paymentId, 'SellerAdmin').then(expectSuccess);

    const pay = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(pay.status).toBe('REVERSED');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('FROZEN');
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);
    expect(cust.balance_due_cents).toBe(10_000);

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('ACCEPTED');
    expect(inv.amount_due_cents).toBe(10_000);
    expect(inv.amount_disputed_cents).toBe(0);

    const all = (await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin')) as any[];
    const sumDue = all
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
    expect(sumDue).toBe(10_000);
    expect(sumDue).toBe(cust.balance_due_cents);
  });

  test('REV_010: reversing a multi-invoice discounted payment voids EARLY_PAY_DISCOUNT and restores both invoice balances', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });

    const iDisc = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 100_000 });
    const iFull = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountDueCents: 50_000 });

    const p = await createPayment(
      workspaceId,
      customerId,
      {
        amount_cents: 148_000,
        allocations: [
          { invoice_id: iDisc, amount_cents: 98_000 },
          { invoice_id: iFull, amount_cents: 50_000 }
        ]
      },
      'BuyerAP'
    );
    const paymentId = getPaymentId(p);
    expect(p.status).toBe('INITIATED');

    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const issued = await listCreditMemos(workspaceId, { customer_id: customerId, status: 'ISSUED' }, 'SellerAdmin');
    const issuedArr = extractListArray(issued);
    const epd = issuedArr.find((cm) => (cm?.type ?? cm?.credit_memo_type ?? cm?.reason) === 'EARLY_PAY_DISCOUNT');
    expect(epd).toBeDefined();
    const epdId = epd?.credit_memo_id ?? epd?.id;
    if (!epdId) throw new Error('Could not resolve EARLY_PAY_DISCOUNT credit memo id');

    const pre = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(pre.balance_due_cents).toBe(0);
    expect(pre.unapplied_cash_cents).toBe(0);
    expect(pre.available_credit_cents).toBe(0);

    await reversePayment(workspaceId, paymentId, 'SellerAdmin').then(expectSuccess);

    const pay = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(pay.status).toBe('REVERSED');

    const epdAfter = await getCreditMemo(workspaceId, epdId, 'SellerAdmin');
    expect(epdAfter.status).toBe('VOIDED');

    const invDisc = await getInvoice(workspaceId, iDisc, 'SellerAdmin');
    expect(invDisc.status).toBe('ACCEPTED');
    expect(invDisc.amount_due_cents).toBe(100_000);
    expect(invDisc.amount_disputed_cents).toBe(0);

    const invFull = await getInvoice(workspaceId, iFull, 'SellerAdmin');
    expect(invFull.status).toBe('ACCEPTED');
    expect(invFull.amount_due_cents).toBe(50_000);
    expect(invFull.amount_disputed_cents).toBe(0);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('FROZEN');
    expect(cust.balance_due_cents).toBe(150_000);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);

    const all = (await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin')) as any[];
    const sumDue = all
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
    expect(sumDue).toBe(150_000);
    expect(sumDue).toBe(cust.balance_due_cents);
  });

  test('REV_011: reversal restores lifecycle state for a FINALIZED (unsent, unaccepted) invoice', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });

    const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `REV-011-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(inv);
    await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/lines`,
      { description: 'Line', quantity_units: 1, unit_price_cents: 10_000 },
      'SellerAR'
    ).then(expectSuccess);
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');

    const fin0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(fin0.status).toBe('FINALIZED');
    expect(fin0.issued_period_index).toBe(0);
    expect(fin0.delivered_period_index == null).toBe(true);
    expect(fin0.accepted_period_index == null).toBe(true);
    expect(fin0.due_period_index == null).toBe(true);
    expect(fin0.amount_due_cents).toBe(10_000);

    const p = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 10_000, allocations: [{ invoice_id: invoiceId, amount_cents: 10_000 }] },
      'BuyerAP'
    );
    const paymentId = getPaymentId(p);
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const closed = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(closed.status).toBe('CLOSED');
    expect(closed.amount_due_cents).toBe(0);

    await reversePayment(workspaceId, paymentId, 'SellerAdmin').then(expectSuccess);

    const pay = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(pay.status).toBe('REVERSED');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('FROZEN');
    expect(cust.balance_due_cents).toBe(10_000);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);

    const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter.status).toBe('FINALIZED');
    expect(invAfter.issued_period_index).toBe(0);
    expect(invAfter.delivered_period_index == null).toBe(true);
    expect(invAfter.accepted_period_index == null).toBe(true);
    expect(invAfter.due_period_index == null).toBe(true);
    expect(invAfter.amount_due_cents).toBe(10_000);
    expect(invAfter.amount_disputed_cents).toBe(0);

    const all = (await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin')) as any[];
    const sumDue = all
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
    expect(sumDue).toBe(10_000);
    expect(sumDue).toBe(cust.balance_due_cents);
  });
});
