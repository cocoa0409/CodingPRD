import { getAs, postAs, postRaw } from '../../../test-helpers/api-client';
import { expectErrorCode, expectSuccess } from '../../../test-helpers/assertions';
import { createSentMatchedInvoice as createSentMatchedInvoiceFixture, setupWorkspaceCustomerContract } from '../../../test-helpers/fixtures';
import {
  acceptInvoice,
  activateContract,
  addInvoiceLine,
  advancePeriod,
  getCreditMemo,
  getCreditMemoId,
  createContract,
  createCustomer,
  createDispute,
  createInvoice,
  createPayment,
  createPurchaseOrder,
  createWorkspace,
  finalizeInvoice,
  freezeCustomer,
  getContractId,
  getDispute,
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
  listCreditMemos,
  listInvoices,
  markPaymentCleared,
  markPaymentFailed,
  recordReceipt,
  reversePayment,
  voidInvoice,
  writeOffInvoice,
  uniqueId
} from '../../../test-helpers/resources';

describe('Idempotency, Auth, and Error Precedence Tests', () => {
  async function createSentMatchedInvoice(workspaceId: string, customerId: string, contractId: string) {
    const { invoiceId } = await createSentMatchedInvoiceFixture({ workspaceId, customerId, contractId, isService: true });
    return invoiceId;
  }

  test('AUTH_001: missing X_Actor headers on mutation fails ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();

    const res = await postRaw(
      `/workspaces/${workspaceId}/customers/${customerId}/invoices`,
      { contract_id: contractId, external_invoice_ref: `INV-${uniqueId('erp')}` }

    );
    await expectErrorCode(res, 'ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER');
  });

  test('AUTH_002: Auditor cannot create invoices (ERR_FORBIDDEN_FOR_ROLE)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();

    const res = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/invoices`,
      { contract_id: contractId, external_invoice_ref: `INV-${uniqueId('erp')}` },
      'Auditor'
    );
    await expectErrorCode(res, 'ERR_FORBIDDEN_FOR_ROLE');
  });

  test('AUTH_003: SellerAR cannot accept invoices (ERR_FORBIDDEN_FOR_ROLE)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createSentMatchedInvoice(workspaceId, customerId, contractId);

    const res = await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/accept`, {}, 'SellerAR');
    await expectErrorCode(res, 'ERR_FORBIDDEN_FOR_ROLE');
  });

  test('AUTH_004: BuyerAP cannot seller_respond (ERR_FORBIDDEN_FOR_ROLE)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createSentMatchedInvoice(workspaceId, customerId, contractId);
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);
    const dispute = await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_units: 1 }] },
      'BuyerAP'
    );
    const disputeId = dispute.dispute_id ?? dispute.id;
    if (!disputeId) throw new Error('Could not resolve dispute_id');

    const res = await postAs(`/workspaces/${workspaceId}/disputes/${disputeId}/seller_respond`, {}, 'BuyerAP');
    await expectErrorCode(res, 'ERR_FORBIDDEN_FOR_ROLE');
  });

  test('AUTH_005: mark_cleared is idempotent with same Idempotency_Key (no double apply)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const payment = await createPayment(workspaceId, customerId, { amount_cents: 10_000 }, 'BuyerAP');
    const paymentId = getPaymentId(payment);

    const snap = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(snap.unapplied_cash_cents).toBe(0);

    const key = 'K1';
    const r1 = await postAs(`/workspaces/${workspaceId}/payments/${paymentId}/mark_cleared`, {}, 'SellerAR', { Idempotency_Key: key });
    expectSuccess(r1);

    const r2 = await postAs(`/workspaces/${workspaceId}/payments/${paymentId}/mark_cleared`, {}, 'SellerAR', { Idempotency_Key: key });
    expectSuccess(r2);
    expect(r2.body).toEqual(r1.body);

    const pay = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(pay.status).toBe('CLEARED');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.unapplied_cash_cents).toBe(10_000);

    expect(contractId).toBeDefined();
  });

  test('AUTH_006: reusing Idempotency_Key with different payload fails ERR_IDEMPOTENCY_CONFLICT', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createSentMatchedInvoice(workspaceId, customerId, contractId);
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const key = 'K1';
    const r1 = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/payments`,
      { amount_cents: 10_000 },
      'BuyerAP',
      { Idempotency_Key: key }
    );
    expectSuccess(r1);

    const r2 = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/payments`,
      { amount_cents: 20_000 },
      'BuyerAP',
      { Idempotency_Key: key }
    );
    await expectErrorCode(r2, 'ERR_IDEMPOTENCY_CONFLICT');
  });

  test('AUTH_007: idempotency conflicts when ledger changed (mark_cleared retried after reversal)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createSentMatchedInvoice(workspaceId, customerId, contractId);
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const due = inv.amount_due_cents as number;
    const payment = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: due, allocations: [{ invoice_id: invoiceId, amount_cents: due }] },
      'BuyerAP'
    );
    const paymentId = getPaymentId(payment);

    const key = 'K2';
    const cleared = await postAs(`/workspaces/${workspaceId}/payments/${paymentId}/mark_cleared`, {}, 'SellerAR', { Idempotency_Key: key });
    expectSuccess(cleared);

    await reversePayment(workspaceId, paymentId, 'SellerAdmin').then(expectSuccess);
    const reopened = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(reopened.amount_due_cents).toBe(due);

    const retry = await postAs(`/workspaces/${workspaceId}/payments/${paymentId}/mark_cleared`, {}, 'SellerAR', { Idempotency_Key: key });
    await expectErrorCode(retry, 'ERR_IDEMPOTENCY_CONFLICT');
  });

  test('TRANS_014: finalize retry with same Idempotency_Key conflicts after void removes duplicate external ref blocker', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const externalRef = 'REF-IDEMP-1';

    const i1 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: externalRef }, 'SellerAR');
    const i1Id = getInvoiceId(i1);
    await addInvoiceLine(workspaceId, i1Id, { description: 'I1', quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, i1Id, {}, 'SellerAR');
    const inv1 = await getInvoice(workspaceId, i1Id, 'SellerAdmin');
    expect(inv1.status).toBe('FINALIZED');

    const i2 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: externalRef }, 'SellerAR');
    const i2Id = getInvoiceId(i2);
    await addInvoiceLine(workspaceId, i2Id, { description: 'I2', quantity_units: 12, unit_price_cents: 1_000 }, 'SellerAR');

    const key = 'K_FIN';
    const first = await postAs(
      `/workspaces/${workspaceId}/invoices/${i2Id}/finalize`,
      { override_hold: false, override_billing_cap: false, final_invoice: false },
      'SellerAR',
      { Idempotency_Key: key }
    );
    await expectErrorCode(first, 'ERR_DUPLICATE_EXTERNAL_REF');

    await voidInvoice(workspaceId, i1Id, 'SellerAR').then(expectSuccess);
    const inv1Voided = await getInvoice(workspaceId, i1Id, 'SellerAdmin');
    expect(inv1Voided.status).toBe('VOIDED');

    const retry = await postAs(
      `/workspaces/${workspaceId}/invoices/${i2Id}/finalize`,
      { override_hold: false, override_billing_cap: false, final_invoice: false },
      'SellerAR',
      { Idempotency_Key: key }
    );
    await expectErrorCode(retry, 'ERR_IDEMPOTENCY_CONFLICT');

    const inv2 = await getInvoice(workspaceId, i2Id, 'SellerAdmin');
    expect(inv2.status).toBe('DRAFT');
    expect(inv2.invoice_total_cents).toBe(0);
    expect(inv2.issued_period_index == null).toBe(true);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);
    expect(cust.unapplied_cash_cents).toBe(0);
  });

  test('TRANS_018: escalated dispute puts customer on CREDIT_HOLD and blocks invoice finalization (ERR_CUSTOMER_ON_HOLD)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });

    const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `T18-I-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(inv);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.status).toBe('ACCEPTED');
    expect(inv0.amount_due_cents).toBe(10_000);
    const lineId = getFirstInvoiceLineId(inv0);

    const dispute = await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: 5_000 }] },
      'BuyerAP'
    );
    const disputeId = dispute.dispute_id ?? dispute.id;
    if (!disputeId) throw new Error('Could not resolve dispute_id');

    const proposed = await postAs(
      `/workspaces/${workspaceId}/disputes/${disputeId}/propose_resolution`,
      { proposed_credit: { items: [{ invoice_line_id: lineId, quantity_units: 1, unit_price_cents: 5_000 }] } },
      'SellerAR'
    );
    expectSuccess(proposed);

    const rej = await postAs(`/workspaces/${workspaceId}/disputes/${disputeId}/reject_resolution`, {}, 'BuyerAP');
    expectSuccess(rej);

    const d = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(d.status).toBe('ESCALATED');

    const inv2 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `T18-I2-${uniqueId('inv')}` }, 'SellerAR');
    const inv2Id = getInvoiceId(inv2);
    await addInvoiceLine(workspaceId, inv2Id, { quantity_units: 5, unit_price_cents: 1_000 }, 'SellerAR');

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${inv2Id}/finalize`,
      { override_hold: false, override_billing_cap: false, final_invoice: false },
      'SellerAR'
    );
    await expectErrorCode(res, 'ERR_CUSTOMER_ON_HOLD');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('CREDIT_HOLD');
    expect(cust.balance_due_cents).toBe(10_000);

    const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter.status).toBe('ACCEPTED');
    expect(invAfter.amount_due_cents).toBe(10_000);
    expect(invAfter.amount_disputed_cents).toBe(5_000);

    const inv2After = await getInvoice(workspaceId, inv2Id, 'SellerAdmin');
    expect(inv2After.status).toBe('DRAFT');
    expect(inv2After.invoice_total_cents).toBe(0);
    expect(inv2After.issued_period_index == null).toBe(true);

    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const sumDue = all
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((acc: number, i: any) => acc + (i.amount_due_cents as number), 0);
    expect(sumDue).toBe(10_000);
    expect(sumDue).toBe(cust.balance_due_cents);
  });

  test('TRANS_019: early-pay discount applies when SellerAR creates+clears the short payment under policy', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });

    const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `T19-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(inv);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const p = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 98_000, allocations: [{ invoice_id: invoiceId, amount_cents: 98_000 }] },
      'SellerAR'
    );
    const paymentId = getPaymentId(p);
    expect(p.status).toBe('INITIATED');

    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const pay = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(pay.status).toBe('CLEARED');

    const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter.status).toBe('CLOSED');
    expect(invAfter.amount_due_cents).toBe(0);
    expect(invAfter.amount_disputed_cents).toBe(0);
    expect(invAfter.accepted_period_index).toBe(0);
    expect(invAfter.due_period_index).toBe(2);

    const issued = await listCreditMemos(workspaceId, { customer_id: customerId, status: 'ISSUED' }, 'SellerAdmin');
    const issuedArr = Array.isArray(issued) ? issued : (issued as any[]) ?? [];
    expect(issuedArr).toHaveLength(1);
    const epd = issuedArr[0];
    const t = epd?.type ?? epd?.credit_memo_type ?? epd?.reason;
    expect(t).toBe('EARLY_PAY_DISCOUNT');

    const epdId = getCreditMemoId(epd);
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
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);

    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const sumDue = all
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((acc: number, i: any) => acc + (i.amount_due_cents as number), 0);
    expect(sumDue).toBe(0);
    expect(sumDue).toBe(cust.balance_due_cents);
  });

  test('TRANS_020: early-pay discount can apply to one invoice within a multi-invoice payment', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });

    const iDisc = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `T20-DISC-${uniqueId('inv')}` }, 'SellerAR');
    const iDiscId = getInvoiceId(iDisc);
    await addInvoiceLine(workspaceId, iDiscId, { quantity_units: 10, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, iDiscId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${iDiscId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, iDiscId, 'BuyerAP').then(expectSuccess);

    const iFull = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `T20-FULL-${uniqueId('inv')}` }, 'SellerAR');
    const iFullId = getInvoiceId(iFull);
    await addInvoiceLine(workspaceId, iFullId, { quantity_units: 5, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, iFullId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${iFullId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, iFullId, 'BuyerAP').then(expectSuccess);

    const p = await createPayment(
      workspaceId,
      customerId,
      {
        amount_cents: 148_000,
        allocations: [
          { invoice_id: iDiscId, amount_cents: 98_000 },
          { invoice_id: iFullId, amount_cents: 50_000 }
        ]
      },
      'BuyerAP'
    );
    const paymentId = getPaymentId(p);
    expect(p.status).toBe('INITIATED');

    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const pay = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(pay.status).toBe('CLEARED');

    const invDisc = await getInvoice(workspaceId, iDiscId, 'SellerAdmin');
    const invFull = await getInvoice(workspaceId, iFullId, 'SellerAdmin');
    expect(invDisc.status).toBe('CLOSED');
    expect(invDisc.amount_due_cents).toBe(0);
    expect(invDisc.amount_disputed_cents).toBe(0);
    expect(invFull.status).toBe('CLOSED');
    expect(invFull.amount_due_cents).toBe(0);
    expect(invFull.amount_disputed_cents).toBe(0);

    const issued = await listCreditMemos(workspaceId, { customer_id: customerId, status: 'ISSUED' }, 'SellerAdmin');
    const issuedArr = Array.isArray(issued) ? issued : (issued as any[]) ?? [];
    expect(issuedArr).toHaveLength(1);
    const epd = issuedArr[0];
    const t = epd?.type ?? epd?.credit_memo_type ?? epd?.reason;
    expect(t).toBe('EARLY_PAY_DISCOUNT');

    const epdId = getCreditMemoId(epd);
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
    expect(epdFull.invoice_id).toBe(iDiscId);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(0);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);

    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const sumDue = all
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((acc: number, i: any) => acc + (i.amount_due_cents as number), 0);
    expect(sumDue).toBe(0);
    expect(sumDue).toBe(cust.balance_due_cents);
  });

  test('TRANS_021: dispute window is acceptance-based; SENT invoice with no acceptance remains disputable after many periods', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1, requires_po: true });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 10, unit_price_cents: 10_000, is_service: false }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId, external_invoice_ref: `T21-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(inv);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);

    const sent0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(sent0.status).toBe('SENT');
    expect(sent0.delivered_period_index).toBe(0);
    expect(sent0.match_status).toBe('EXCEPTION');
    expect(sent0.accepted_period_index == null).toBe(true);
    expect(sent0.due_period_index == null).toBe(true);

    for (let i = 0; i < 10; i++) {
      await advancePeriod(workspaceId, 'System');
    }
    const ws = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(ws.period_index).toBe(10);

    const sent = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(sent.status).toBe('SENT');
    expect(sent.accepted_period_index == null).toBe(true);
    expect(sent.due_period_index == null).toBe(true);

    const lineId = getFirstInvoiceLineId(sent);
    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/disputes`,
      { reason: 'MISSING_RECEIPT', items: [{ invoice_line_id: lineId, disputed_units: 10 }] },
      'BuyerAP'
    );
    expectSuccess(res, 201);
    const created = res.body?.data ?? res.body;
    const disputeId = created.dispute_id ?? created.id;
    if (!disputeId) throw new Error('Could not resolve dispute_id');

    const d = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(d.status).toBe('OPEN');
    expect(d.reason).toBe('MISSING_RECEIPT');

    const after = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(after.status).toBe('SENT');
    expect(after.amount_disputed_cents).toBe(100_000);
    expect(after.accepted_period_index == null).toBe(true);
    expect(after.due_period_index == null).toBe(true);
    expect(after.amount_disputed_cents).toBeGreaterThanOrEqual(0);
    expect(after.amount_disputed_cents).toBeLessThanOrEqual(after.amount_due_cents);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(100_000);

    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const sumDue = all
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((acc: number, i: any) => acc + (i.amount_due_cents as number), 0);
    expect(sumDue).toBe(100_000);
    expect(sumDue).toBe(cust.balance_due_cents);
  });

  test('TRANS_101: auto-allocation can close a SENT invoice without setting acceptance/due fields', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2, requires_po: false });

    const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `T101-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(inv);
    await addInvoiceLine(workspaceId, invoiceId, { description: 'Line', quantity_units: 1, unit_price_cents: 50_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);

    const sent = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(sent.status).toBe('SENT');
    expect(sent.delivered_period_index).toBe(0);
    expect(sent.accepted_period_index == null).toBe(true);
    expect(sent.due_period_index == null).toBe(true);
    expect(sent.amount_due_cents).toBe(50_000);

    const p = await createPayment(workspaceId, customerId, { amount_cents: 50_000 }, 'BuyerAP');
    const paymentId = getPaymentId(p);
    expect(p.status).toBe('INITIATED');
    const reserved = (p.allocations ?? (p as any).reserved_allocations ?? (p as any).reserved ?? []) as any[];
    expect(reserved).toHaveLength(1);
    expect(reserved[0].invoice_id).toBe(invoiceId);
    expect(reserved[0].amount_cents).toBe(50_000);

    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const pay = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(pay.status).toBe('CLEARED');

    const after = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(after.status).toBe('CLOSED');
    expect(after.amount_due_cents).toBe(0);
    expect(after.amount_disputed_cents).toBe(0);
    expect(after.delivered_period_index).toBe(0);
    expect(after.accepted_period_index == null).toBe(true);
    expect(after.due_period_index == null).toBe(true);

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

  test('TRANS_102: reserved allocation does not expand at clearing even if invoice becomes MATCHED while payment is INITIATED', async () => {
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

    const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId, external_invoice_ref: `T102-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(inv);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);

    const sent0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(sent0.status).toBe('SENT');
    expect(sent0.delivered_period_index).toBe(0);
    expect(sent0.match_status).toBe('EXCEPTION');
    expect(sent0.amount_due_cents).toBe(100_000);

    const p = await createPayment(workspaceId, customerId, { amount_cents: 100_000 }, 'BuyerAP');
    const payId = getPaymentId(p);
    expect(p.status).toBe('INITIATED');
    const reserved = (p.allocations ?? (p as any).reserved_allocations ?? (p as any).reserved ?? []) as any[];
    expect(reserved).toHaveLength(1);
    expect(reserved[0].invoice_id).toBe(invoiceId);
    expect(reserved[0].amount_cents).toBe(50_000);

    await recordReceipt(workspaceId, poId, [{ purchase_order_line_id: poLineId, received_units: 5 }], 'BuyerAP').then(expectSuccess);
    const matched = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(matched.match_status).toBe('MATCHED');

    await markPaymentCleared(workspaceId, payId, 'SellerAR');

    const pay = await getPayment(workspaceId, payId, 'SellerAdmin');
    expect(pay.status).toBe('CLEARED');

    const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter.status).toBe('SENT');
    expect(invAfter.match_status).toBe('MATCHED');
    expect(invAfter.amount_due_cents).toBe(50_000);
    expect(invAfter.amount_disputed_cents).toBe(0);
    expect(invAfter.accepted_period_index == null).toBe(true);
    expect(invAfter.due_period_index == null).toBe(true);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(50_000);
    expect(cust.unapplied_cash_cents).toBe(50_000);
    expect(cust.available_credit_cents).toBe(0);

    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const sumDue = (all as any[])
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
    expect(sumDue).toBe(50_000);
    expect(sumDue).toBe(cust.balance_due_cents);
  });

  test('TRANS_103: a CLOSED invoice is not eligible for deemed acceptance and keeps accepted/due fields unset', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1, requires_po: false });

    const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `T103-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(inv);
    await addInvoiceLine(workspaceId, invoiceId, { description: 'Line', quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);

    await advancePeriod(workspaceId, 'System');

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
    expect(closed.accepted_period_index == null).toBe(true);
    expect(closed.due_period_index == null).toBe(true);

    const out = await advancePeriod(workspaceId, 'System');
    const ids = ((out as any).finance_charge_invoice_ids ?? []) as string[];
    expect(ids).toHaveLength(0);

    const after = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(after.status).toBe('CLOSED');
    expect(after.amount_due_cents).toBe(0);
    expect(after.accepted_period_index == null).toBe(true);
    expect(after.due_period_index == null).toBe(true);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(0);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);
  });

  test('TRANS_104: close_books retry with same Idempotency_Key after ledger changes fails ERR_IDEMPOTENCY_CONFLICT', async () => {
    const workspace = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
    const workspaceId = workspace.workspace_id;
    const customer = await createCustomer(workspaceId, {}, 'SellerAdmin');
    const customerId = getCustomerId(customer);

    const p0 = await createPayment(workspaceId, customerId, { amount_cents: 1_000 }, 'BuyerAP');
    const p0Id = getPaymentId(p0);
    expect(p0.status).toBe('INITIATED');

    await advancePeriod(workspaceId, 'System');

    const key = 'K_CB_PENDING';
    const first = await postAs(`/workspaces/${workspaceId}/close_books`, {}, 'Auditor', { Idempotency_Key: key });
    await expectErrorCode(first, 'ERR_PERIOD_HAS_PENDING_PAYMENTS');
    const ws0 = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(ws0.period_index).toBe(1);
    expect(ws0.books_closed_through_period_index == null).toBe(true);

    await markPaymentCleared(workspaceId, p0Id, 'SellerAR');
    const pay0 = await getPayment(workspaceId, p0Id, 'SellerAdmin');
    expect(pay0.status).toBe('CLEARED');

    const cust0 = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust0.unapplied_cash_cents).toBe(1_000);

    const retry = await postAs(`/workspaces/${workspaceId}/close_books`, {}, 'Auditor', { Idempotency_Key: key });
    await expectErrorCode(retry, 'ERR_IDEMPOTENCY_CONFLICT');

    const wsAfter = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(wsAfter.period_index).toBe(1);
    expect(wsAfter.books_closed_through_period_index == null).toBe(true);

    const payAfter = await getPayment(workspaceId, p0Id, 'SellerAdmin');
    expect(payAfter.status).toBe('CLEARED');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(0);
    expect(cust.unapplied_cash_cents).toBe(1_000);
    expect(cust.available_credit_cents).toBe(0);
  });

  test('TRANS_105: accepted dispute resolution can make invoice MATCHED and then be deemed accepted on next period close; PO net_billed_units updates', async () => {
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

    const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId, external_invoice_ref: `T105-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(inv);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 12, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);

    const sent0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(sent0.status).toBe('SENT');
    expect(sent0.delivered_period_index).toBe(0);
    expect(sent0.match_status).toBe('EXCEPTION');
    expect(sent0.amount_due_cents).toBe(120_000);
    const invoiceLineId = getFirstInvoiceLineId(sent0);

    const dRes = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/disputes`,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_units: 2 }] },
      'BuyerAP'
    );
    expectSuccess(dRes, 201);
    const dBody = dRes.body?.data ?? dRes.body;
    const disputeId = dBody.dispute_id ?? dBody.id;
    if (!disputeId) throw new Error('Could not resolve dispute_id');

    const invDisputed = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invDisputed.amount_disputed_cents).toBe(20_000);

    await postAs(
      `/workspaces/${workspaceId}/disputes/${disputeId}/propose_resolution`,
      { proposed_credit: { items: [{ invoice_line_id: invoiceLineId, quantity_units: 2, unit_price_cents: 10_000 }] } },
      'SellerAR'
    ).then(expectSuccess);

    await postAs(`/workspaces/${workspaceId}/disputes/${disputeId}/accept_resolution`, {}, 'BuyerAP').then(expectSuccess);

    const dClosed = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(dClosed.status).toBe('CLOSED');

    const afterResolution = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(afterResolution.status).toBe('SENT');
    expect(afterResolution.amount_due_cents).toBe(100_000);
    expect(afterResolution.amount_disputed_cents).toBe(0);
    expect(afterResolution.match_status).toBe('MATCHED');

    const cms = await listCreditMemos(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const arr = Array.isArray(cms) ? cms : (cms as any)?.items ?? (cms as any)?.data ?? [];
    const issued = (arr as any[]).find((cm: any) => cm.status === 'ISSUED' && (cm.invoice_id ?? cm.invoiceId) === invoiceId);
    if (!issued) throw new Error('Expected an ISSUED credit memo applied from accept_resolution');
    const cmId = getCreditMemoId(issued);
    const cmFull = await getCreditMemo(workspaceId, cmId, 'SellerAdmin');
    expect(cmFull.status).toBe('ISSUED');

    const poAfter = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    expect(poAfter.lines[0].net_billed_units).toBe(10);

    await advancePeriod(workspaceId, 'System');
    const out = await advancePeriod(workspaceId, 'System');
    expect((out as any).period_index).toBe(2);

    const accepted = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(accepted.status).toBe('ACCEPTED');
    expect(accepted.accepted_period_index).toBe(1);
    expect(accepted.due_period_index).toBe(2);
    expect(accepted.delivered_period_index).toBe(0);
    expect(accepted.match_status).toBe('MATCHED');
    expect(accepted.amount_due_cents).toBe(100_000);
    expect(accepted.amount_disputed_cents).toBe(0);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(100_000);
    expect(cust.available_credit_cents).toBe(0);
    expect(cust.unapplied_cash_cents).toBe(0);

    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const sumDue = (all as any[])
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
    expect(sumDue).toBe(100_000);
    expect(sumDue).toBe(cust.balance_due_cents);
  });

  test('TRANS_106: finance charges are computed on remaining overdue amount after cleared payments', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1, requires_po: false });

    const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `T106-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(inv);
    await addInvoiceLine(workspaceId, invoiceId, { description: 'Line', quantity_units: 30, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const p = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 100_000, allocations: [{ invoice_id: invoiceId, amount_cents: 100_000 }] },
      'BuyerAP'
    );
    const paymentId = getPaymentId(p);
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const invAfterPay = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfterPay.status).toBe('ACCEPTED');
    expect(invAfterPay.amount_due_cents).toBe(200_000);

    const before = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(before.balance_due_cents).toBe(200_000);

    const out = await advancePeriod(workspaceId, 'System');
    const ids = ((out as any).finance_charge_invoice_ids ?? []) as string[];
    expect(ids).toHaveLength(1);
    const financeId = ids[0];

    const f = await getInvoice(workspaceId, financeId, 'SellerAdmin');
    expect(f.type).toBe('FINANCE_CHARGE');
    expect(f.status).toBe('ACCEPTED');
    expect(f.reference_invoice_id).toBe(invoiceId);
    expect(f.issued_period_index).toBe(3);
    expect(f.delivered_period_index).toBe(3);
    expect(f.accepted_period_index).toBe(3);
    expect(f.due_period_index).toBe(4);
    expect(f.invoice_total_cents).toBe(3_000);
    expect(f.amount_due_cents).toBe(3_000);

    const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter.amount_due_cents).toBe(200_000);
    expect(invAfter.collections_stage).toBe('FINAL_NOTICE');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(203_000);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);

    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const sumDue = (all as any[])
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
    expect(sumDue).toBe(203_000);
    expect(sumDue).toBe(cust.balance_due_cents);
  });

  test('TRANS_201: SENT EXCEPTION invoice has no due date, no collections stage escalation, and never generates finance charges', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: true, payment_terms_periods: 1 });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 300, unit_price_cents: 10_000, is_service: false }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId, external_invoice_ref: `T201-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(inv);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 300, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);

    for (let i = 0; i < 5; i++) {
      await advancePeriod(workspaceId, 'System');
    }
    const ws = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(ws.period_index).toBe(5);

    const preCharges = await listInvoices(workspaceId, { customer_id: customerId, type: 'FINANCE_CHARGE' }, 'SellerAdmin');
    expect(preCharges).toHaveLength(0);

    const out = await advancePeriod(workspaceId, 'System');
    expect((out as any).period_index).toBe(6);
    const ids = ((out as any).finance_charge_invoice_ids ?? []) as string[];
    expect(ids).toHaveLength(0);

    const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter.status).toBe('SENT');
    expect(invAfter.match_status).toBe('EXCEPTION');
    expect(invAfter.accepted_period_index == null).toBe(true);
    expect(invAfter.due_period_index == null).toBe(true);
    expect(invAfter.collections_stage).toBe('CURRENT');
    expect(invAfter.amount_due_cents).toBe(3_000_000);
    expect(invAfter.amount_disputed_cents).toBe(0);

    const charges = await listInvoices(workspaceId, { customer_id: customerId, type: 'FINANCE_CHARGE' }, 'SellerAdmin');
    expect(charges).toHaveLength(0);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('ACTIVE');
    expect(cust.balance_due_cents).toBe(3_000_000);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);

    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const sumDue = (all as any[])
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
    expect(sumDue).toBe(3_000_000);
    expect(sumDue).toBe(cust.balance_due_cents);
  });

  test('TRANS_202: no-allocation payment auto-allocates to the oldest overdue invoice (not a SENT invoice with no due date)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: false, payment_terms_periods: 1 });

    const iOver = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `T202-OVER-${uniqueId('inv')}` }, 'SellerAR');
    const iOverId = getInvoiceId(iOver);
    await addInvoiceLine(workspaceId, iOverId, { description: 'Overdue', quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, iOverId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${iOverId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, iOverId, 'BuyerAP').then(expectSuccess);

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');
    const over0 = await getInvoice(workspaceId, iOverId, 'SellerAdmin');
    expect(over0.collections_stage).toBe('REMINDER');

    const iSent = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `T202-SENT-${uniqueId('inv')}` }, 'SellerAR');
    const iSentId = getInvoiceId(iSent);
    await addInvoiceLine(workspaceId, iSentId, { description: 'No due yet', quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, iSentId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${iSentId}/send`, {}, 'SellerAR').then(expectSuccess);

    const sent0 = await getInvoice(workspaceId, iSentId, 'SellerAdmin');
    expect(sent0.status).toBe('SENT');
    expect(sent0.accepted_period_index == null).toBe(true);
    expect(sent0.due_period_index == null).toBe(true);
    expect(sent0.amount_due_cents).toBe(10_000);

    const p = await createPayment(workspaceId, customerId, { amount_cents: 10_000 }, 'BuyerAP');
    const paymentId = getPaymentId(p);
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const overAfter = await getInvoice(workspaceId, iOverId, 'SellerAdmin');
    expect(overAfter.status).toBe('CLOSED');
    expect(overAfter.amount_due_cents).toBe(0);

    const sentAfter = await getInvoice(workspaceId, iSentId, 'SellerAdmin');
    expect(sentAfter.status).toBe('SENT');
    expect(sentAfter.amount_due_cents).toBe(10_000);
    expect(sentAfter.accepted_period_index == null).toBe(true);
    expect(sentAfter.due_period_index == null).toBe(true);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(10_000);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);

    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const sumDue = (all as any[])
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
    expect(sumDue).toBe(10_000);
    expect(sumDue).toBe(cust.balance_due_cents);
  });

  test('AUTH_008: Idempotency_Key is workspace-scoped (same key can be reused in different workspaces)', async () => {
    const w1 = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
    const w2 = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
    const c1 = await createCustomer(w1.workspace_id, {}, 'SellerAdmin');
    const c2 = await createCustomer(w2.workspace_id, {}, 'SellerAdmin');

    const key = 'K3';
    const p1 = await postAs(
      `/workspaces/${w1.workspace_id}/customers/${getCustomerId(c1)}/payments`,
      { amount_cents: 10_000 },
      'BuyerAP',
      { Idempotency_Key: key }
    );
    expectSuccess(p1);

    const p2 = await postAs(
      `/workspaces/${w2.workspace_id}/customers/${getCustomerId(c2)}/payments`,
      { amount_cents: 10_000 },
      'BuyerAP',
      { Idempotency_Key: key }
    );
    expectSuccess(p2);
  });

  test('AUTH_009: customer frozen wins first for BuyerAP paying and disputing (ERR_CUSTOMER_FROZEN)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createSentMatchedInvoice(workspaceId, customerId, contractId);
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const due = inv.amount_due_cents as number;
    const payment = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: due, allocations: [{ invoice_id: invoiceId, amount_cents: due }] },
      'BuyerAP'
    );
    const paymentId = getPaymentId(payment);
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');
    await reversePayment(workspaceId, paymentId, 'SellerAdmin').then(expectSuccess);
    const custFrozen = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custFrozen.status).toBe('FROZEN');

    const payRes = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/payments`,
      { amount_cents: 1000, allocations: [{ invoice_id: invoiceId, amount_cents: 1000 }] },
      'BuyerAP'
    );
    await expectErrorCode(payRes, 'ERR_CUSTOMER_FROZEN');

    const invNow = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(invNow);
    const disputeRes = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/disputes`,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_units: 1 }] },
      'BuyerAP'
    );
    await expectErrorCode(disputeRes, 'ERR_CUSTOMER_FROZEN');
  });

  test('AUTH_010: invoice acceptance returns ERR_MATCH_EXCEPTION even if other timing logic could apply', async () => {
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

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 12, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const res = await acceptInvoice(workspaceId, invoiceId, 'BuyerAP');
    await expectErrorCode(res, 'ERR_MATCH_EXCEPTION');
  });

  test('AUTH_011: finalize error precedence: ERR_CUSTOMER_ON_HOLD wins over ERR_PO_REQUIRED', async () => {
    const ws = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
    const workspaceId = ws.workspace_id;
    const customer = await createCustomer(workspaceId, {}, 'SellerAdmin');
    const customerId = getCustomerId(customer);

    const kReq = await createContract(
      workspaceId,
      customerId,
      { name: `K-REQ-${uniqueId('k')}`, payment_terms_periods: 2, requires_po: true, billing_cap_cents_per_period: 10_000_000 },
      'SellerAdmin'
    );
    const kReqId = getContractId(kReq);
    await activateContract(workspaceId, kReqId, 'SellerAdmin');

    const kFree = await createContract(
      workspaceId,
      customerId,
      { name: `K-FREE-${uniqueId('k')}`, payment_terms_periods: 1, requires_po: false, billing_cap_cents_per_period: 10_000_000 },
      'SellerAdmin'
    );
    const kFreeId = getContractId(kFree);
    await activateContract(workspaceId, kFreeId, 'SellerAdmin');

    const invBig = await createInvoice(workspaceId, customerId, { contract_id: kFreeId, external_invoice_ref: `HOLD-${uniqueId('inv')}` }, 'SellerAR');
    const invBigId = getInvoiceId(invBig);
    await addInvoiceLine(workspaceId, invBigId, { quantity_units: 300, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invBigId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invBigId}/send`, {}, 'SellerAR').then(expectSuccess);
    await postAs(`/workspaces/${workspaceId}/invoices/${invBigId}/accept`, {}, 'BuyerAP').then(expectSuccess);

    const invAccepted = await getInvoice(workspaceId, invBigId, 'SellerAdmin');
    const duePeriod = invAccepted.due_period_index as number;
    while (true) {
      const w = await getWorkspace(workspaceId, 'SellerAdmin');
      if (w.period_index >= duePeriod + 1) break;
      await advancePeriod(workspaceId, 'System');
    }
    const custHold = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custHold.status).toBe('CREDIT_HOLD');

    const inv = await createInvoice(workspaceId, customerId, { contract_id: kReqId }, 'SellerAR');
    const invId = getInvoiceId(inv);
    await addInvoiceLine(workspaceId, invId, { quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invId}/finalize`,
      { override_hold: false, override_billing_cap: false, final_invoice: false },
      'SellerAR'
    );
    await expectErrorCode(res, 'ERR_CUSTOMER_ON_HOLD');
  });

  test('AUTH_012: dispute creation precedence: ERR_COLLECTIONS_RESTRICTS_DISPUTES wins over dispute window', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1 });
    const invoiceId = await createSentMatchedInvoice(workspaceId, customerId, contractId);
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const duePeriod = inv0.due_period_index as number;

    while (true) {
      const ws = await getWorkspace(workspaceId, 'SellerAdmin');
      if (ws.period_index >= duePeriod + 5) break;
      await advancePeriod(workspaceId, 'System');
    }

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.collections_stage).toBe('COLLECTIONS');
    const invoiceLineId = getFirstInvoiceLineId(inv);

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/disputes`,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_units: 1 }] },
      'BuyerAP'
    );
    await expectErrorCode(res, 'ERR_COLLECTIONS_RESTRICTS_DISPUTES');
  });

  test('AUTH_013: frozen wins over invoice not payable (frozen customer paying a VOIDED invoice => ERR_CUSTOMER_FROZEN)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await voidInvoice(workspaceId, invoiceId, 'SellerAR').then(expectSuccess);

    await freezeCustomer(workspaceId, customerId, 'MANUAL', 'SellerAdmin').then(expectSuccess);

    const res = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/payments`,
      { amount_cents: 1000, allocations: [{ invoice_id: invoiceId, amount_cents: 1000 }] },
      'BuyerAP'
    );
    await expectErrorCode(res, 'ERR_CUSTOMER_FROZEN');
  });

  test('AUTH_014: active customer paying a VOIDED invoice fails ERR_INVOICE_NOT_PAYABLE', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await voidInvoice(workspaceId, invoiceId, 'SellerAR').then(expectSuccess);

    const res = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/payments`,
      { amount_cents: 1000, allocations: [{ invoice_id: invoiceId, amount_cents: 1000 }] },
      'BuyerAP'
    );
    await expectErrorCode(res, 'ERR_INVOICE_NOT_PAYABLE');
  });

  test('AUTH_015: negative disputed_units is ERR_INVALID_REQUEST', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoiceId = await createSentMatchedInvoice(workspaceId, customerId, contractId);

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/disputes`,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_units: -1 }] },
      'BuyerAP'
    );
    await expectErrorCode(res, 'ERR_INVALID_REQUEST');
  });

  test('AUTH_016: unknown invoice id returns ERR_NOT_FOUND', async () => {
    const { workspaceId } = await setupWorkspaceCustomerContract();
    const res = await getAs(`/workspaces/${workspaceId}/invoices/unknown-${uniqueId('inv')}`, 'SellerAdmin');
    await expectErrorCode(res, 'ERR_NOT_FOUND');
  });

  test('AUTH_018: repeated mark_failed is ERR_INVALID_STATE_TRANSITION', async () => {
    const { workspaceId, customerId } = await (async () => {
      const ws = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
      const cust = await createCustomer(ws.workspace_id, {}, 'SellerAdmin');
      return { workspaceId: ws.workspace_id, customerId: getCustomerId(cust) };
    })();

    const payment = await createPayment(workspaceId, customerId, { amount_cents: 10_000 }, 'BuyerAP');
    const paymentId = getPaymentId(payment);
    await markPaymentFailed(workspaceId, paymentId, 'SellerAR');

    const res = await postAs(`/workspaces/${workspaceId}/payments/${paymentId}/mark_failed`, {}, 'SellerAR');
    await expectErrorCode(res, 'ERR_INVALID_STATE_TRANSITION');
  });

  test('AUTH_019: SellerAR cannot reverse payments (ERR_FORBIDDEN_FOR_ROLE) even if already reversed', async () => {
    const { workspaceId, customerId } = await (async () => {
      const ws = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
      const cust = await createCustomer(ws.workspace_id, {}, 'SellerAdmin');
      return { workspaceId: ws.workspace_id, customerId: getCustomerId(cust) };
    })();

    const payment = await createPayment(workspaceId, customerId, { amount_cents: 10_000 }, 'BuyerAP');
    const paymentId = getPaymentId(payment);
    await postAs(`/workspaces/${workspaceId}/payments/${paymentId}/mark_cleared`, {}, 'SellerAR').then(expectSuccess);
    await reversePayment(workspaceId, paymentId, 'SellerAdmin').then(expectSuccess);

    const res = await postAs(`/workspaces/${workspaceId}/payments/${paymentId}/reverse`, {}, 'SellerAR');
    await expectErrorCode(res, 'ERR_FORBIDDEN_FOR_ROLE');
  });

  test('AUTH_020: write_off on DRAFT invoice fails ERR_WRITE_OFF_NOT_ALLOWED', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();
    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);

    const res = await writeOffInvoice(workspaceId, invoiceId, 'SellerAR');
    await expectErrorCode(res, 'ERR_WRITE_OFF_NOT_ALLOWED');
  });

  test('ERR_001: SellerAdmin void after books closed fails ERR_BOOKS_CLOSED if any payment ever CLEARED (even if later REVERSED)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `ERR1-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.status).toBe('FINALIZED');
    expect(inv0.issued_period_index).toBe(0);

    const p = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 5_000, allocations: [{ invoice_id: invoiceId, amount_cents: 5_000 }] },
      'BuyerAP'
    );
    const paymentId = getPaymentId(p);
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');
    const invPaid = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invPaid.amount_due_cents).toBe(5_000);

    await advancePeriod(workspaceId, 'System');
    const close = await postAs(`/workspaces/${workspaceId}/close_books`, {}, 'Auditor');
    expectSuccess(close);
    const ws = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(ws.books_closed_through_period_index).toBe(0);

    await reversePayment(workspaceId, paymentId, 'SellerAdmin').then(expectSuccess);
    const invReopened = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invReopened.amount_due_cents).toBe(10_000);

    const res = await voidInvoice(workspaceId, invoiceId, 'SellerAdmin');
    await expectErrorCode(res, 'ERR_BOOKS_CLOSED');

    const invStill = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invStill.status).toBe('FINALIZED');
    expect(invStill.amount_due_cents).toBe(10_000);
  });

  test('ERR_002: frozen customer acceptance is blocked with ERR_CUSTOMER_FROZEN and invoice remains SENT', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `FROZEN-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);

    const before = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(before.status).toBe('SENT');

    const pay = await createPayment(workspaceId, customerId, { amount_cents: 10_000 }, 'BuyerAP');
    const payId = getPaymentId(pay);
    await markPaymentCleared(workspaceId, payId, 'SellerAR');
    await reversePayment(workspaceId, payId, 'SellerAdmin').then(expectSuccess);
    const custFrozen = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custFrozen.status).toBe('FROZEN');

    const res = await acceptInvoice(workspaceId, invoiceId, 'BuyerAP');
    await expectErrorCode(res, 'ERR_CUSTOMER_FROZEN');

    const after = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(after.status).toBe('SENT');
    expect(after.accepted_period_index == null).toBe(true);
    expect(after.due_period_index == null).toBe(true);
  });

  test('ERR_008: frozen customer acceptance returns ERR_CUSTOMER_FROZEN even if invoice has match exceptions', async () => {
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

    const invoice = await createInvoice(
      workspaceId,
      customerId,
      { contract_id: contractId, purchase_order_id: poId, external_invoice_ref: `ERR8-${uniqueId('inv')}` },
      'SellerAR'
    );
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);

    const sent = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(sent.status).toBe('SENT');
    expect(sent.match_status).toBe('EXCEPTION');
    expect(sent.accepted_period_index == null).toBe(true);
    expect(sent.due_period_index == null).toBe(true);

    const pay = await createPayment(workspaceId, customerId, { amount_cents: 1_000 }, 'BuyerAP');
    const payId = getPaymentId(pay);
    await markPaymentCleared(workspaceId, payId, 'SellerAR');
    await reversePayment(workspaceId, payId, 'SellerAdmin').then(expectSuccess);
    const frozen = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(frozen.status).toBe('FROZEN');

    const res = await acceptInvoice(workspaceId, invoiceId, 'BuyerAP');
    await expectErrorCode(res, 'ERR_CUSTOMER_FROZEN');

    const after = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(after.status).toBe('SENT');
    expect(after.match_status).toBe('EXCEPTION');
    expect(after.accepted_period_index == null).toBe(true);
    expect(after.due_period_index == null).toBe(true);
  });

  test('ERR_009: frozen customer wins over collections dispute restriction (ERR_CUSTOMER_FROZEN)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1 });

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `ERR9-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 1_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/accept`, {}, 'BuyerAP').then(expectSuccess);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const lineId = getFirstInvoiceLineId(inv0);
    const dFull = await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: 10_000 }] },
      'BuyerAP'
    );
    const disputeId = dFull.dispute_id ?? dFull.id;
    if (!disputeId) throw new Error('Could not resolve dispute_id');

    while (true) {
      const w = await getWorkspace(workspaceId, 'SellerAdmin');
      if (w.period_index >= 4) break;
      await advancePeriod(workspaceId, 'System');
    }

    await postAs(`/workspaces/${workspaceId}/disputes/${disputeId}/withdraw`, {}, 'BuyerAP').then(expectSuccess);
    const invUndisputed = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invUndisputed.amount_disputed_cents).toBe(0);
    expect(invUndisputed.collections_stage).toBe('COLLECTIONS');

    const p = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 1_000, allocations: [{ invoice_id: invoiceId, amount_cents: 1_000 }] },
      'BuyerAP'
    );
    const paymentId = getPaymentId(p);
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');
    await reversePayment(workspaceId, paymentId, 'SellerAdmin').then(expectSuccess);

    const custFrozen = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custFrozen.status).toBe('FROZEN');

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/disputes`,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: 1_000 }] },
      'BuyerAP'
    );
    await expectErrorCode(res, 'ERR_CUSTOMER_FROZEN');

    const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter.amount_disputed_cents).toBe(0);
    expect(invAfter.collections_stage).toBe('COLLECTIONS');

    const custAfter = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custAfter.status).toBe('FROZEN');
    expect(custAfter.balance_due_cents).toBe(10_000);
    expect(custAfter.unapplied_cash_cents).toBe(0);
    expect(custAfter.available_credit_cents).toBe(0);

    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const sumDue = (all as any[])
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
    expect(sumDue).toBe(10_000);
    expect(sumDue).toBe(custAfter.balance_due_cents);
  });

  test("ERR_010: customer frozen wins first for BuyerAP re-accepting an ACCEPTED invoice (ERR_CUSTOMER_FROZEN)", async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1 });

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `ERR10-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.status).toBe('ACCEPTED');
    expect(inv0.accepted_period_index).toBe(0);
    expect(inv0.due_period_index).toBe(1);
    expect(inv0.amount_due_cents).toBe(10_000);

    const p0 = await createPayment(workspaceId, customerId, { amount_cents: 1_000 }, 'BuyerAP');
    const p0Id = getPaymentId(p0);
    await markPaymentCleared(workspaceId, p0Id, 'SellerAR');
    await reversePayment(workspaceId, p0Id, 'SellerAdmin').then(expectSuccess);
    const frozen = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(frozen.status).toBe('FROZEN');

    const res = await acceptInvoice(workspaceId, invoiceId, 'BuyerAP');
    await expectErrorCode(res, 'ERR_CUSTOMER_FROZEN');

    const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter.status).toBe('ACCEPTED');
    expect(invAfter.accepted_period_index).toBe(0);
    expect(invAfter.due_period_index).toBe(1);
    expect(invAfter.amount_due_cents).toBe(10_000);
    expect(invAfter.amount_disputed_cents).toBe(0);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('FROZEN');
    expect(cust.balance_due_cents).toBe(10_000);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);

    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const sumDue = (all as any[])
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
    expect(sumDue).toBe(10_000);
    expect(sumDue).toBe(cust.balance_due_cents);
  });

  test('ERR_011: applying an invoice-tied credit memo to a different invoice fails ERR_INVALID_REQUEST and changes nothing', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });

    const i1 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `ERR11-I1-${uniqueId('inv')}` }, 'SellerAR');
    const i1Id = getInvoiceId(i1);
    await addInvoiceLine(workspaceId, i1Id, { quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, i1Id, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${i1Id}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, i1Id, 'BuyerAP').then(expectSuccess);

    const i2 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `ERR11-I2-${uniqueId('inv')}` }, 'SellerAR');
    const i2Id = getInvoiceId(i2);
    await addInvoiceLine(workspaceId, i2Id, { quantity_units: 1, unit_price_cents: 12_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, i2Id, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${i2Id}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, i2Id, 'BuyerAP').then(expectSuccess);

    const inv1 = await getInvoice(workspaceId, i1Id, 'SellerAdmin');
    const inv2 = await getInvoice(workspaceId, i2Id, 'SellerAdmin');
    const l1 = getFirstInvoiceLineId(inv1);
    expect(inv1.amount_due_cents).toBe(10_000);
    expect(inv2.amount_due_cents).toBe(12_000);

    const cmRes = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/credit_memos`,
      { invoice_id: i1Id, reason: 'GOODWILL', items: [{ invoice_line_id: l1, quantity_units: 1, unit_price_cents: 5_000 }] },
      'SellerAR'
    );
    expectSuccess(cmRes);
    const cmBody = cmRes.body?.data ?? cmRes.body;
    const cmId = cmBody.credit_memo_id ?? cmBody.id;
    if (!cmId) throw new Error('Could not resolve credit_memo_id');

    await postAs(`/workspaces/${workspaceId}/credit_memos/${cmId}/issue`, {}, 'SellerAR').then(expectSuccess);

    const cust0 = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust0.available_credit_cents).toBe(5_000);
    expect(cust0.balance_due_cents).toBe(22_000);

    const applyRes = await postAs(`/workspaces/${workspaceId}/credit_memos/${cmId}/apply`, { invoice_id: i2Id }, 'SellerAR');
    await expectErrorCode(applyRes, 'ERR_INVALID_REQUEST');

    const cmAfter = await getCreditMemo(workspaceId, cmId, 'SellerAdmin');
    expect(cmAfter.status).toBe('ISSUED');

    const i1After = await getInvoice(workspaceId, i1Id, 'SellerAdmin');
    const i2After = await getInvoice(workspaceId, i2Id, 'SellerAdmin');
    expect(i1After.amount_due_cents).toBe(10_000);
    expect(i2After.amount_due_cents).toBe(12_000);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(22_000);
    expect(cust.available_credit_cents).toBe(5_000);
    expect(cust.unapplied_cash_cents).toBe(0);

    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const sumDue = (all as any[])
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
    expect(sumDue).toBe(22_000);
    expect(sumDue).toBe(cust.balance_due_cents);
  });

  test('ERR_003: void precedence returns ERR_INVOICE_HAS_PAYMENTS even when books are closed through issue period', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `ERR3-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.status).toBe('FINALIZED');
    expect(inv0.issued_period_index).toBe(0);
    expect(inv0.amount_due_cents).toBe(10_000);

    await advancePeriod(workspaceId, 'System');
    await postAs(`/workspaces/${workspaceId}/close_books`, {}, 'Auditor').then(expectSuccess);
    const ws = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(ws.books_closed_through_period_index).toBe(0);

    const p = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 5_000, allocations: [{ invoice_id: invoiceId, amount_cents: 5_000 }] },
      'BuyerAP'
    );
    const paymentId = getPaymentId(p);
    const pay0 = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(pay0.status).toBe('INITIATED');

    const res = await voidInvoice(workspaceId, invoiceId, 'SellerAR');
    await expectErrorCode(res, 'ERR_INVOICE_HAS_PAYMENTS');

    const invStill = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invStill.status).toBe('FINALIZED');
    expect(invStill.amount_due_cents).toBe(10_000);

    const wsStill = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(wsStill.books_closed_through_period_index).toBe(0);

    const payStill = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(payStill.status).toBe('INITIATED');
  });

  test('ERR_004: void precedence returns ERR_INVOICE_HAS_DISPUTE even if invoice also has INITIATED payment', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `ERR4-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 2, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/accept`, {}, 'BuyerAP').then(expectSuccess);

    const payment = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 10_000, allocations: [{ invoice_id: invoiceId, amount_cents: 10_000 }] },
      'BuyerAP'
    );
    const paymentId = getPaymentId(payment);
    const pay0 = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(pay0.status).toBe('INITIATED');

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const lineId = getFirstInvoiceLineId(inv0);
    await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: 5_000 }] },
      'BuyerAP'
    );

    const res = await voidInvoice(workspaceId, invoiceId, 'SellerAdmin');
    await expectErrorCode(res, 'ERR_INVOICE_HAS_DISPUTE');

    const inv1 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv1.status).toBe('ACCEPTED');
    expect(inv1.amount_due_cents).toBe(20_000);
    expect(inv1.amount_disputed_cents).toBe(5_000);

    const pay1 = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(pay1.status).toBe('INITIATED');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(20_000);
  });

  test('INV_204: Idempotency_Key reuse across different endpoints does not conflict', async () => {
    const ws = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
    const workspaceId = ws.workspace_id;
    const customer = await createCustomer(workspaceId, {}, 'SellerAdmin');
    const customerId = getCustomerId(customer);

    const key = 'K_SAME';
    const createPoRes = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/purchase_orders`,
      {
        po_number: 'PO-IDEMP-1',
        lines: [{ description: 'Widgets', ordered_units: 10, unit_price_cents: 10_000, is_service: false }]
      },
      'BuyerAP',
      { Idempotency_Key: key }
    );
    expectSuccess(createPoRes);
    const createdPo = createPoRes.body?.data ?? createPoRes.body;
    const poId = getPurchaseOrderId(createdPo);

    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    expect(poFull.status).toBe('OPEN');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    const receiptRes = await postAs(
      `/workspaces/${workspaceId}/purchase_orders/${poId}/record_receipt`,
      { items: [{ purchase_order_line_id: poLineId, received_units: 5 }] },
      'BuyerAP',
      { Idempotency_Key: key }
    );
    expectSuccess(receiptRes);

    const poAfter = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    expect(poAfter.status).toBe('OPEN');
    const line = (poAfter.lines as any[]).find((l: any) => (l.purchase_order_line_id ?? l.id ?? l.line_id) === poLineId);
    expect(line).toBeDefined();
    expect(line.received_units).toBe(5);
    expect(line.net_billed_units).toBe(0);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);
    expect(cust.unapplied_cash_cents).toBe(0);
  });

  test('ERR_005: valid hold override reveals ERR_PO_REQUIRED (not ERR_CUSTOMER_ON_HOLD)', async () => {
    const ws = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
    const workspaceId = ws.workspace_id;
    const customer = await createCustomer(workspaceId, {}, 'SellerAdmin');
    const customerId = getCustomerId(customer);

    const kHold = await createContract(
      workspaceId,
      customerId,
      { name: `K-HOLD-${uniqueId('k')}`, payment_terms_periods: 1, requires_po: false, billing_cap_cents_per_period: 10_000_000 },
      'SellerAdmin'
    );
    const kHoldId = getContractId(kHold);
    await activateContract(workspaceId, kHoldId, 'SellerAdmin');

    const iHold = await createInvoice(workspaceId, customerId, { contract_id: kHoldId, external_invoice_ref: `I-HOLD-${uniqueId('inv')}` }, 'SellerAR');
    const iHoldId = getInvoiceId(iHold);
    await addInvoiceLine(workspaceId, iHoldId, { description: 'Hold', quantity_units: 260, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, iHoldId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${iHoldId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, iHoldId, 'BuyerAP').then(expectSuccess);

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const invHold = await getInvoice(workspaceId, iHoldId, 'SellerAdmin');
    expect(invHold.collections_stage).toBe('REMINDER');

    const custHold = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custHold.status).toBe('CREDIT_HOLD');
    expect(custHold.balance_due_cents).toBe(2_600_000);

    const kReq = await createContract(
      workspaceId,
      customerId,
      { name: `K-REQ-${uniqueId('k')}`, payment_terms_periods: 1, requires_po: true, billing_cap_cents_per_period: 10_000_000 },
      'SellerAdmin'
    );
    const kReqId = getContractId(kReq);
    await activateContract(workspaceId, kReqId, 'SellerAdmin');

    const iNew = await createInvoice(workspaceId, customerId, { contract_id: kReqId, external_invoice_ref: `I-NEW-${uniqueId('inv')}` }, 'SellerAR');
    const iNewId = getInvoiceId(iNew);
    await addInvoiceLine(workspaceId, iNewId, { description: 'New', quantity_units: 50, unit_price_cents: 10_000 }, 'SellerAR');

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${iNewId}/finalize`,
      { override_hold: true, override_billing_cap: false, final_invoice: false },
      'SellerAdmin'
    );
    await expectErrorCode(res, 'ERR_PO_REQUIRED');

    const invNew = await getInvoice(workspaceId, iNewId, 'SellerAdmin');
    expect(invNew.status).toBe('DRAFT');
    expect(invNew.invoice_total_cents).toBe(0);
    expect(invNew.issued_period_index == null).toBe(true);

    const custAfter = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custAfter.status).toBe('CREDIT_HOLD');
    expect(custAfter.balance_due_cents).toBe(2_600_000);

    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const sumDue = all
      .filter((inv: any) => inv.status !== 'DRAFT' && inv.status !== 'VOIDED')
      .reduce((acc: number, inv: any) => acc + (inv.amount_due_cents as number), 0);
    expect(sumDue).toBe(2_600_000);
    expect(sumDue).toBe(custAfter.balance_due_cents);
  });

  test('ERR_006: valid hold override reveals ERR_BILLING_CAP_EXCEEDED when cap would be exceeded in-period', async () => {
    const ws = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
    const workspaceId = ws.workspace_id;
    const customer = await createCustomer(workspaceId, {}, 'SellerAdmin');
    const customerId = getCustomerId(customer);

    const kHold = await createContract(
      workspaceId,
      customerId,
      { name: `K-HOLD-${uniqueId('k')}`, payment_terms_periods: 1, requires_po: false, billing_cap_cents_per_period: 10_000_000 },
      'SellerAdmin'
    );
    const kHoldId = getContractId(kHold);
    await activateContract(workspaceId, kHoldId, 'SellerAdmin');

    const iHold = await createInvoice(workspaceId, customerId, { contract_id: kHoldId, external_invoice_ref: `I-HOLD-${uniqueId('inv')}` }, 'SellerAR');
    const iHoldId = getInvoiceId(iHold);
    await addInvoiceLine(workspaceId, iHoldId, { description: 'Hold', quantity_units: 260, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, iHoldId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${iHoldId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, iHoldId, 'BuyerAP').then(expectSuccess);

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const custHold = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custHold.status).toBe('CREDIT_HOLD');

    const kCap = await createContract(
      workspaceId,
      customerId,
      { name: `K-CAP-${uniqueId('k')}`, payment_terms_periods: 2, requires_po: false, billing_cap_cents_per_period: 600_000 },
      'SellerAdmin'
    );
    const kCapId = getContractId(kCap);
    await activateContract(workspaceId, kCapId, 'SellerAdmin');

    const iCap1 = await createInvoice(workspaceId, customerId, { contract_id: kCapId, external_invoice_ref: `CAP1-${uniqueId('inv')}` }, 'SellerAR');
    const iCap1Id = getInvoiceId(iCap1);
    await addInvoiceLine(workspaceId, iCap1Id, { description: 'Cap1', quantity_units: 59, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, iCap1Id, { override_hold: true, override_billing_cap: false }, 'SellerAdmin');

    const iCap2 = await createInvoice(workspaceId, customerId, { contract_id: kCapId, external_invoice_ref: `CAP2-${uniqueId('inv')}` }, 'SellerAR');
    const iCap2Id = getInvoiceId(iCap2);
    await addInvoiceLine(workspaceId, iCap2Id, { description: 'Cap2', quantity_units: 2, unit_price_cents: 10_000 }, 'SellerAR');

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${iCap2Id}/finalize`,
      { override_hold: true, override_billing_cap: false, final_invoice: false },
      'SellerAdmin'
    );
    await expectErrorCode(res, 'ERR_BILLING_CAP_EXCEEDED');

    const invCap2 = await getInvoice(workspaceId, iCap2Id, 'SellerAdmin');
    expect(invCap2.status).toBe('DRAFT');
    expect(invCap2.invoice_total_cents).toBe(0);
    expect(invCap2.issued_period_index == null).toBe(true);

    const invCap1 = await getInvoice(workspaceId, iCap1Id, 'SellerAdmin');
    expect(invCap1.status).toBe('FINALIZED');
    expect(invCap1.issued_period_index).toBe(2);
    expect(invCap1.invoice_total_cents).toBe(590_000);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(3_190_000);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);

    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const capSum = all
      .filter((inv: any) => inv.contract_id === kCapId && inv.issued_period_index === 2)
      .reduce((acc: number, inv: any) => acc + (inv.invoice_total_cents as number), 0);
    expect(capSum).toBe(590_000);
    expect(capSum).toBeLessThanOrEqual(600_000);
  });

  test('ERR_007: payment error precedence returns ERR_INVOICE_NOT_PAYABLE before allocation math', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();

    const iClosed = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `CLOSED-${uniqueId('inv')}` }, 'SellerAR');
    const iClosedId = getInvoiceId(iClosed);
    await addInvoiceLine(workspaceId, iClosedId, { description: 'Closed', quantity_units: 1, unit_price_cents: 5_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, iClosedId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${iClosedId}/send`, {}, 'SellerAR').then(expectSuccess);
    await postAs(`/workspaces/${workspaceId}/invoices/${iClosedId}/accept`, {}, 'BuyerAP').then(expectSuccess);
    const pClose = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 5_000, allocations: [{ invoice_id: iClosedId, amount_cents: 5_000 }] },
      'BuyerAP'
    );
    await markPaymentCleared(workspaceId, getPaymentId(pClose), 'SellerAR');

    const invClosed = await getInvoice(workspaceId, iClosedId, 'SellerAdmin');
    expect(invClosed.status).toBe('CLOSED');
    expect(invClosed.amount_due_cents).toBe(0);

    const i2 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `I2-${uniqueId('inv')}` }, 'SellerAR');
    const i2Id = getInvoiceId(i2);
    await addInvoiceLine(workspaceId, i2Id, { description: 'I2', quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, i2Id, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${i2Id}/send`, {}, 'SellerAR').then(expectSuccess);
    await postAs(`/workspaces/${workspaceId}/invoices/${i2Id}/accept`, {}, 'BuyerAP').then(expectSuccess);

    const inv2Pre = await getInvoice(workspaceId, i2Id, 'SellerAdmin');
    const lineId = getFirstInvoiceLineId(inv2Pre);
    await createDispute(
      workspaceId,
      i2Id,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: 8_000 }] },
      'BuyerAP'
    );

    const snap = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(snap.balance_due_cents).toBe(10_000);
    expect(snap.unapplied_cash_cents).toBe(0);

    const res = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/payments`,
      {
        amount_cents: 6_000,
        allocations: [
          { invoice_id: iClosedId, amount_cents: 1_000 },
          { invoice_id: i2Id, amount_cents: 5_000 }
        ]
      },
      'BuyerAP'
    );
    await expectErrorCode(res, 'ERR_INVOICE_NOT_PAYABLE');

    const invClosedAfter = await getInvoice(workspaceId, iClosedId, 'SellerAdmin');
    expect(invClosedAfter.status).toBe('CLOSED');
    expect(invClosedAfter.amount_due_cents).toBe(0);

    const inv2After = await getInvoice(workspaceId, i2Id, 'SellerAdmin');
    expect(inv2After.status).toBe('ACCEPTED');
    expect(inv2After.amount_due_cents).toBe(10_000);
    expect(inv2After.amount_disputed_cents).toBe(8_000);

    const custAfter = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custAfter.balance_due_cents).toBe(10_000);
    expect(custAfter.unapplied_cash_cents).toBe(0);
    expect(custAfter.available_credit_cents).toBe(0);
  });

  test('INV_101: advance_period is idempotent with same Idempotency_Key (no double-advance, no double finance-charge issuance)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1 });

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `INV101-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/accept`, {}, 'BuyerAP').then(expectSuccess);

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const snap = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(snap.balance_due_cents).toBe(100_000);

    const key = 'K_ADV';
    const r1 = await postAs(`/workspaces/${workspaceId}/advance_period`, {}, 'System', { Idempotency_Key: key });
    expectSuccess(r1);
    const r2 = await postAs(`/workspaces/${workspaceId}/advance_period`, {}, 'System', { Idempotency_Key: key });
    expectSuccess(r2);
    expect(r2.body).toEqual(r1.body);

    const d1 = r1.body?.data ?? r1.body;
    expect(d1.period_index).toBe(3);
    const financeIds = (d1.finance_charge_invoice_ids ?? []) as string[];
    expect(financeIds).toHaveLength(1);
    const f = financeIds[0];

    const ws = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(ws.period_index).toBe(3);

    const financeCharges = await listInvoices(workspaceId, { customer_id: customerId, type: 'FINANCE_CHARGE' }, 'SellerAdmin');
    expect(financeCharges).toHaveLength(1);
    expect(getInvoiceId(financeCharges[0])).toBe(f);
    expect(financeCharges[0].invoice_total_cents).toBe(2_500);
    expect(financeCharges[0].issued_period_index).toBe(3);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(102_500);
  });

  test('INV_102: close_books is idempotent with same Idempotency_Key (replay returns original success, not ERR_INVALID_STATE_TRANSITION)', async () => {
    const ws0 = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
    const workspaceId = ws0.workspace_id;

    await advancePeriod(workspaceId, 'System');

    const pre = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(pre.period_index).toBe(1);
    expect(pre.books_closed_through_period_index).toBe(null);

    const key = 'K_CB';
    const r1 = await postAs(`/workspaces/${workspaceId}/close_books`, {}, 'Auditor', { Idempotency_Key: key });
    expectSuccess(r1);
    const r2 = await postAs(`/workspaces/${workspaceId}/close_books`, {}, 'Auditor', { Idempotency_Key: key });
    expectSuccess(r2);
    expect(r2.body).toEqual(r1.body);

    const d1 = r1.body?.data ?? r1.body;
    expect(d1.books_closed_through_period_index).toBe(0);

    const ws = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(ws.period_index).toBe(1);
    expect(ws.books_closed_through_period_index).toBe(0);
  });

  test('INV_103: applying a line-tied credit reduces amount_disputed_cents but is capped at the disputed amount', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: false, payment_terms_periods: 1 });

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `INV103-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 2, unit_price_cents: 5_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const lineId = getFirstInvoiceLineId(inv0);

    await createDispute(workspaceId, invoiceId, { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: 3_000 }] }, 'BuyerAP');

    const cmRes = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/credit_memos`,
      { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: lineId, quantity_units: 1, unit_price_cents: 5_000 }] },
      'SellerAR'
    );
    expectSuccess(cmRes);
    const cm = cmRes.body?.data ?? cmRes.body;
    const cmId = cm.credit_memo_id ?? cm.id;
    if (!cmId) throw new Error('Could not resolve credit_memo_id');

    await postAs(`/workspaces/${workspaceId}/credit_memos/${cmId}/issue`, {}, 'SellerAR').then(expectSuccess);
    await postAs(`/workspaces/${workspaceId}/credit_memos/${cmId}/apply`, { invoice_id: invoiceId }, 'SellerAR').then(expectSuccess);

    const inv1 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv1.status).toBe('ACCEPTED');
    expect(inv1.amount_due_cents).toBe(5_000);
    expect(inv1.amount_disputed_cents).toBe(0);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(5_000);
    expect(cust.available_credit_cents).toBe(0);
    expect(inv1.amount_disputed_cents).toBeGreaterThanOrEqual(0);
    expect(inv1.amount_disputed_cents).toBeLessThanOrEqual(inv1.amount_due_cents);
  });

  test('INV_104: goodwill per-period cap is per customer (issuing for C2 succeeds even if C1 hit its cap)', async () => {
    const ws = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
    const workspaceId = ws.workspace_id;

    const c1 = await createCustomer(workspaceId, {}, 'SellerAdmin');
    const c2 = await createCustomer(workspaceId, {}, 'SellerAdmin');
    const c1Id = getCustomerId(c1);
    const c2Id = getCustomerId(c2);

    for (const qty of [10, 10, 5]) {
      const cmRes = await postAs(
        `/workspaces/${workspaceId}/customers/${c1Id}/credit_memos`,
        { reason: 'GOODWILL', items: [{ quantity_units: qty, unit_price_cents: 10_000 }] },
        'SellerAR'
      );
      expectSuccess(cmRes);
      const cm = cmRes.body?.data ?? cmRes.body;
      const cmId = cm.credit_memo_id ?? cm.id;
      if (!cmId) throw new Error('Could not resolve credit_memo_id for C1');
      await postAs(`/workspaces/${workspaceId}/credit_memos/${cmId}/issue`, {}, 'SellerAR').then(expectSuccess);
    }

    const c1Snap = await getCustomer(workspaceId, c1Id, 'SellerAdmin');
    expect(c1Snap.available_credit_cents).toBe(250_000);

    const gw4Res = await postAs(
      `/workspaces/${workspaceId}/customers/${c2Id}/credit_memos`,
      { reason: 'GOODWILL', items: [{ quantity_units: 10, unit_price_cents: 10_000 }] },
      'SellerAR'
    );
    expectSuccess(gw4Res);
    const gw4 = gw4Res.body?.data ?? gw4Res.body;
    const gw4Id = gw4.credit_memo_id ?? gw4.id;
    if (!gw4Id) throw new Error('Could not resolve credit_memo_id for C2');

    const issueRes = await postAs(`/workspaces/${workspaceId}/credit_memos/${gw4Id}/issue`, {}, 'SellerAR');
    expectSuccess(issueRes);

    const gotGw4 = await getAs(`/workspaces/${workspaceId}/credit_memos/${gw4Id}`, 'SellerAdmin');
    expectSuccess(gotGw4);
    const gw4Body = gotGw4.body?.data ?? gotGw4.body;
    expect(gw4Body.status).toBe('ISSUED');

    const c2Snap = await getCustomer(workspaceId, c2Id, 'SellerAdmin');
    expect(c2Snap.available_credit_cents).toBe(100_000);
    expect(c2Snap.balance_due_cents).toBe(0);
    expect(c2Snap.unapplied_cash_cents).toBe(0);

    const c1After = await getCustomer(workspaceId, c1Id, 'SellerAdmin');
    expect(c1After.available_credit_cents).toBe(250_000);
  });

  test('INV_105: external_invoice_ref uniqueness is per customer (duplicates across customers allowed)', async () => {
    const ws = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
    const workspaceId = ws.workspace_id;

    const c1 = await createCustomer(workspaceId, {}, 'SellerAdmin');
    const c2 = await createCustomer(workspaceId, {}, 'SellerAdmin');
    const c1Id = getCustomerId(c1);
    const c2Id = getCustomerId(c2);

    const k1 = await createContract(workspaceId, c1Id, { requires_po: false, payment_terms_periods: 2 }, 'SellerAdmin');
    const k2 = await createContract(workspaceId, c2Id, { requires_po: false, payment_terms_periods: 2 }, 'SellerAdmin');
    const k1Id = getContractId(k1);
    const k2Id = getContractId(k2);
    await activateContract(workspaceId, k1Id, 'SellerAdmin');
    await activateContract(workspaceId, k2Id, 'SellerAdmin');

    const externalRef = 'REF-X';

    const i1 = await createInvoice(workspaceId, c1Id, { contract_id: k1Id, external_invoice_ref: externalRef }, 'SellerAR');
    const i1Id = getInvoiceId(i1);
    await addInvoiceLine(workspaceId, i1Id, { quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, i1Id, {}, 'SellerAR');

    const i2 = await createInvoice(workspaceId, c2Id, { contract_id: k2Id, external_invoice_ref: externalRef }, 'SellerAR');
    const i2Id = getInvoiceId(i2);
    await addInvoiceLine(workspaceId, i2Id, { quantity_units: 12, unit_price_cents: 1_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, i2Id, {}, 'SellerAR');

    const inv2 = await getInvoice(workspaceId, i2Id, 'SellerAdmin');
    expect(inv2.status).toBe('FINALIZED');
    expect(inv2.invoice_total_cents).toBe(12_000);
    expect(inv2.external_invoice_ref).toBe(externalRef);

    const inv1 = await getInvoice(workspaceId, i1Id, 'SellerAdmin');
    expect(inv1.status).toBe('FINALIZED');
    expect(inv1.external_invoice_ref).toBe(externalRef);

    const cust1 = await getCustomer(workspaceId, c1Id, 'SellerAdmin');
    const cust2 = await getCustomer(workspaceId, c2Id, 'SellerAdmin');
    expect(cust1.balance_due_cents).toBe(10_000);
    expect(cust2.balance_due_cents).toBe(12_000);
  });

  test('INV_106: failed payment creation leaves no partial reservations; subsequent valid allocation succeeds', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: false, payment_terms_periods: 1 });

    async function createAccepted(amount: number, ref: string) {
      const i = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: ref }, 'SellerAR');
      const id = getInvoiceId(i);
      await addInvoiceLine(workspaceId, id, { quantity_units: 1, unit_price_cents: amount }, 'SellerAR');
      await finalizeInvoice(workspaceId, id, {}, 'SellerAR');
      await postAs(`/workspaces/${workspaceId}/invoices/${id}/send`, {}, 'SellerAR').then(expectSuccess);
      await acceptInvoice(workspaceId, id, 'BuyerAP').then(expectSuccess);
      return id;
    }

    const i1 = await createAccepted(5_000, `INV106-1-${uniqueId('inv')}`);
    const i2 = await createAccepted(5_000, `INV106-2-${uniqueId('inv')}`);

    const snap = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(snap.balance_due_cents).toBe(10_000);

    const step1 = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/payments`,
      { amount_cents: 11_000, allocations: [{ invoice_id: i1, amount_cents: 5_000 }, { invoice_id: i2, amount_cents: 6_000 }] },
      'BuyerAP'
    );
    await expectErrorCode(step1, 'ERR_PAYMENT_EXCEEDS_ALLOWED');

    const step2 = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/payments`,
      { amount_cents: 5_000, allocations: [{ invoice_id: i1, amount_cents: 5_000 }] },
      'BuyerAP'
    );
    expectSuccess(step2);
    const created = step2.body?.data ?? step2.body;
    expect(created.status).toBe('INITIATED');

    const inv1 = await getInvoice(workspaceId, i1, 'SellerAdmin');
    const inv2 = await getInvoice(workspaceId, i2, 'SellerAdmin');
    expect(inv1.amount_due_cents).toBe(5_000);
    expect(inv2.amount_due_cents).toBe(5_000);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(10_000);
  });

  test('INV_107: invoice IDs are workspace-scoped; cross-workspace GET returns ERR_NOT_FOUND', async () => {
    const w1 = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
    const w2 = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
    const w1Id = w1.workspace_id;
    const w2Id = w2.workspace_id;

    const c1 = await createCustomer(w1Id, {}, 'SellerAdmin');
    const c1Id = getCustomerId(c1);
    const k1 = await createContract(w1Id, c1Id, { requires_po: false, payment_terms_periods: 2 }, 'SellerAdmin');
    const k1Id = getContractId(k1);
    await activateContract(w1Id, k1Id, 'SellerAdmin');

    const inv = await createInvoice(w1Id, c1Id, { contract_id: k1Id, external_invoice_ref: `INV107-${uniqueId('inv')}` }, 'SellerAR');
    const invId = getInvoiceId(inv);
    await addInvoiceLine(w1Id, invId, { quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(w1Id, invId, {}, 'SellerAR');

    const c2 = await createCustomer(w2Id, {}, 'SellerAdmin');
    const c2Id = getCustomerId(c2);
    const k2 = await createContract(w2Id, c2Id, { requires_po: false, payment_terms_periods: 2 }, 'SellerAdmin');
    const k2Id = getContractId(k2);
    await activateContract(w2Id, k2Id, 'SellerAdmin');

    const invsW2 = await listInvoices(w2Id, { customer_id: c2Id }, 'SellerAdmin');
    expect(invsW2).toEqual([]);

    const res = await getAs(`/workspaces/${w2Id}/invoices/${invId}`, 'SellerAdmin');
    await expectErrorCode(res, 'ERR_NOT_FOUND');

    const inW1 = await getInvoice(w1Id, invId, 'SellerAdmin');
    expect(inW1.status).toBe('FINALIZED');
    expect(inW1.amount_due_cents).toBe(10_000);

    const c2After = await getCustomer(w2Id, c2Id, 'SellerAdmin');
    expect(c2After.balance_due_cents).toBe(0);
    expect(c2After.available_credit_cents).toBe(0);
    expect(c2After.unapplied_cash_cents).toBe(0);
  });
});
