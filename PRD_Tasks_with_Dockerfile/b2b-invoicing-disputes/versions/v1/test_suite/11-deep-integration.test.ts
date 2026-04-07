import { postAs } from '../../../test-helpers/api-client';
import { expectErrorCode, expectSuccess } from '../../../test-helpers/assertions';
import { advanceToPeriod, setupWorkspaceCustomerContract } from '../../../test-helpers/fixtures';
import {
  acceptInvoice,
  acceptResolution,
  activateContract,
  addInvoiceLine,
  advancePeriod,
  applyCreditMemo,
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
  getContractId,
  issueCreditMemo,
  listCreditMemos,
  listInvoices,
  markPaymentCleared,
  proposeResolution,
  recordReceipt,
  recompute,
  reversePayment,
  unfreezeCustomer,
  uniqueId,
  voidInvoice,
  withdrawDispute,
  writeOffInvoice
} from '../../../test-helpers/resources';

describe('Deep Integration Tests', () => {
  async function advanceToCollections(workspaceId: string, invoiceId: string) {
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const duePeriod = inv.due_period_index as number;
    await advanceToPeriod(workspaceId, duePeriod + 3);
    const inv2 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv2.collections_stage).toBe('COLLECTIONS');
  }

  test('DEEP_001: full PO/matching/dispute/payment lifecycle ends with clean customer ledger', async () => {
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

    await postAs(`/workspaces/${workspaceId}/purchase_orders/${poId}/record_receipt`, { items: [{ purchase_order_line_id: poLineId, received_units: 5 }] }, 'BuyerAP').then(
      expectSuccess
    );

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);

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

    const p1 = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 50_000, allocations: [{ invoice_id: invoiceId, amount_cents: 50_000 }] },
      'BuyerAP'
    );
    await markPaymentCleared(workspaceId, getPaymentId(p1), 'SellerAR');

    await postAs(`/workspaces/${workspaceId}/purchase_orders/${poId}/record_receipt`, { items: [{ purchase_order_line_id: poLineId, received_units: 5 }] }, 'BuyerAP').then(
      expectSuccess
    );
    await withdrawDispute(workspaceId, disputeId, 'BuyerAP');

    const invAfterWithdraw = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfterWithdraw.amount_disputed_cents).toBe(0);

    const p2 = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 50_000, allocations: [{ invoice_id: invoiceId, amount_cents: 50_000 }] },
      'BuyerAP'
    );
    await markPaymentCleared(workspaceId, getPaymentId(p2), 'SellerAR');

    await advancePeriod(workspaceId, 'System');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(0);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);
    expect(cust.status).toBe('ACTIVE');
  });

  test('DEEP_002: finance charge is created once; no new finance charge after undisputed overdue is paid to zero', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: false, payment_terms_periods: 1 });

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
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.amount_due_cents).toBe(100_000);
    expect(inv0.due_period_index).toBe(1);

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');
    const firstChargeAdvance = await advancePeriod(workspaceId, 'System');
    expect(firstChargeAdvance.finance_charge_invoice_ids).toHaveLength(1);
    const financeChargeId = firstChargeAdvance.finance_charge_invoice_ids[0];

    const chargesAfterFirst = await listInvoices(workspaceId, { customer_id: customerId, type: 'FINANCE_CHARGE' }, 'SellerAdmin');
    expect(chargesAfterFirst.map(getInvoiceId).sort()).toEqual([financeChargeId]);

    const inv1 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv1);
    await createDispute(workspaceId, invoiceId, { reason: 'TAX_ERROR', items: [{ invoice_line_id: invoiceLineId, disputed_amount_cents: 50_000 }] }, 'BuyerAP');

    const p = await createPayment(workspaceId, customerId, { amount_cents: 50_000, allocations: [{ invoice_id: invoiceId, amount_cents: 50_000 }] }, 'BuyerAP');
    await markPaymentCleared(workspaceId, getPaymentId(p), 'SellerAR');

    const secondAdvance = await advancePeriod(workspaceId, 'System');
    expect(secondAdvance.finance_charge_invoice_ids).toHaveLength(0);

    const chargesAfterSecond = await listInvoices(workspaceId, { customer_id: customerId, type: 'FINANCE_CHARGE' }, 'SellerAdmin');
    expect(chargesAfterSecond.map(getInvoiceId).sort()).toEqual([financeChargeId]);
  });

  test('DEEP_003: early-pay discount then reversal then corrective credit ends with ACTIVE customer and zero balances after two advances', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: false, payment_terms_periods: 2 });

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
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const discountedPayment = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 98_000, allocations: [{ invoice_id: invoiceId, amount_cents: 98_000 }] },
      'BuyerAP'
    );
    const paymentId = getPaymentId(discountedPayment);
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const invClosed = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invClosed.status).toBe('CLOSED');
    expect(invClosed.amount_due_cents).toBe(0);

    await reversePayment(workspaceId, paymentId, 'SellerAdmin').then(expectSuccess);

    const custFrozen = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custFrozen.status).toBe('FROZEN');

    const invReopened = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invReopened.amount_due_cents).toBe(100_000);

    const lineId = getFirstInvoiceLineId(invReopened);
    const cm = await createCreditMemo(
      workspaceId,
      customerId,
      { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: lineId, quantity_units: 10, unit_price_cents: 10_000 }] },
      'SellerAdmin'
    );
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAdmin');
    await applyCreditMemo(workspaceId, cmId, invoiceId, 'SellerAdmin');

    const invSettled = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invSettled.status).toBe('CLOSED');
    expect(invSettled.amount_due_cents).toBe(0);

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('ACTIVE');
    expect(cust.balance_due_cents).toBe(0);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);
  });

  test('DEEP_004: admin can override billing cap and (when eligible) override hold to finalize', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({
      requires_po: false,
      payment_terms_periods: 2,
      billing_cap_cents_per_period: 10_000_000
    });

    const inv1 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `CAP-1` }, 'SellerAR');
    const inv1Id = getInvoiceId(inv1);
    await addInvoiceLine(workspaceId, inv1Id, { quantity_units: 1000, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, inv1Id, {}, 'SellerAR');

    const kHold = await createContract(
      workspaceId,
      customerId,
      { name: `Contract-hold`, requires_po: false, payment_terms_periods: 2, billing_cap_cents_per_period: 10_000_000 },
      'SellerAdmin'
    );
    const kHoldId = kHold.contract_id ?? kHold.id;
    await activateContract(workspaceId, kHoldId, 'SellerAdmin');

    const po = await createPurchaseOrder(workspaceId, customerId, { lines: [{ ordered_units: 1, unit_price_cents: 10_000, is_service: true }] }, 'BuyerAP');
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);
    const invDisputed = await createInvoice(workspaceId, customerId, { contract_id: kHoldId, purchase_order_id: poId }, 'SellerAR');
    const invDisputedId = getInvoiceId(invDisputed);
    await addInvoiceLine(workspaceId, invDisputedId, { quantity_units: 1, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invDisputedId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invDisputedId}/send`, {}, 'SellerAR').then(expectSuccess);
    const invD = await getInvoice(workspaceId, invDisputedId, 'SellerAdmin');
    const lineId = getFirstInvoiceLineId(invD);
    const dispute = await createDispute(workspaceId, invDisputedId, { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_units: 1 }] }, 'BuyerAP');
    const disputeId = getDisputeId(dispute);
    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');
    const d = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(d.status).toBe('ESCALATED');

    await proposeResolution(
      workspaceId,
      disputeId,
      { proposed_credit: { items: [{ invoice_line_id: lineId, quantity_units: 1, unit_price_cents: 10_000 }] } },
      'SellerAdmin'
    );
    const acceptRes = await acceptResolution(workspaceId, disputeId, 'BuyerAP');
    expectSuccess(acceptRes);

    const invNew = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `CAP-NEW` }, 'SellerAR');
    const invNewId = getInvoiceId(invNew);
    await addInvoiceLine(workspaceId, invNewId, { quantity_units: 90, unit_price_cents: 10_000 }, 'SellerAR');

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invNewId}/finalize`,
      { override_hold: true, override_billing_cap: true, final_invoice: false },
      'SellerAdmin'
    );
    expectSuccess(res);
    const got = await getInvoice(workspaceId, invNewId, 'SellerAdmin');
    expect(got.status).toBe('FINALIZED');
  });

  test('DEEP_005: dispute->credit correction enables acceptance; close_books succeeds with no pending initiated payments', async () => {
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

    const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId }, 'SellerAR');
    const invoiceId = getInvoiceId(inv);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 103, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.match_status).toBe('EXCEPTION');
    const lineId = getFirstInvoiceLineId(inv0);

    const dispute = await createDispute(workspaceId, invoiceId, { reason: 'PRICE_MISMATCH', items: [{ invoice_line_id: lineId, disputed_units: 3 }] }, 'BuyerAP');
    const disputeId = getDisputeId(dispute);
    await proposeResolution(
      workspaceId,
      disputeId,
      { proposed_credit: { items: [{ invoice_line_id: lineId, quantity_units: 3, unit_price_cents: 10_000 }] } },
      'SellerAR'
    );
    const acc = await acceptResolution(workspaceId, disputeId, 'BuyerAP');
    expectSuccess(acc);

    const inv1 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv1.match_status).toBe('MATCHED');

    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);
    const inv2 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const due = inv2.amount_due_cents as number;

    const payment = await createPayment(workspaceId, customerId, { amount_cents: due, allocations: [{ invoice_id: invoiceId, amount_cents: due }] }, 'BuyerAP');
    await markPaymentCleared(workspaceId, getPaymentId(payment), 'SellerAR');

    await advancePeriod(workspaceId, 'System');
    const close = await closeBooks(workspaceId, 'Auditor');
    expectSuccess(close);
    const ws = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(ws.books_closed_through_period_index).toBe(0);
  });

  test('DEEP_006: clearing after dispute applies only payable amount; remainder becomes unapplied cash', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: false, payment_terms_periods: 2 });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 5, unit_price_cents: 10_000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 5, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const p = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 50_000, allocations: [{ invoice_id: invoiceId, amount_cents: 50_000 }] },
      'BuyerAP'
    );
    const paymentId = getPaymentId(p);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv0);
    await createDispute(workspaceId, invoiceId, { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_amount_cents: 20_000 }] }, 'BuyerAP');

    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const inv1 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv1.amount_disputed_cents).toBe(20_000);
    expect(inv1.amount_due_cents).toBe(20_000);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.unapplied_cash_cents).toBe(20_000);
    expect(cust.balance_due_cents).toBe(20_000);
  });

  test('DEEP_007: fraud dispute freeze lasts until two advances after dispute closure', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: false, payment_terms_periods: 1 });

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
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 1, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    await advanceToCollections(workspaceId, invoiceId);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const lineId = getFirstInvoiceLineId(inv0);
    const dispute = await createDispute(workspaceId, invoiceId, { reason: 'FRAUD', items: [{ invoice_line_id: lineId, disputed_units: 1 }] }, 'BuyerAP');
    const disputeId = getDisputeId(dispute);

    const frozen = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(frozen.status).toBe('FROZEN');

    await proposeResolution(
      workspaceId,
      disputeId,
      { proposed_credit: { items: [{ invoice_line_id: lineId, quantity_units: 1, unit_price_cents: 10_000 }] } },
      'SellerAdmin'
    );
    const acc = await acceptResolution(workspaceId, disputeId, 'BuyerAP');
    expectSuccess(acc);

    const invClosed = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invClosed.status).toBe('CLOSED');

    await advancePeriod(workspaceId, 'System');
    const stillFrozen = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(stillFrozen.status).toBe('FROZEN');

    await advancePeriod(workspaceId, 'System');
    const active = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(active.status).toBe('ACTIVE');
  });

  test('DEEP_008: reversal undoes overpayment-created unapplied cash and freezes customer', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: false, payment_terms_periods: 2 });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,

      { lines: [{ ordered_units: 2, unit_price_cents: 10_000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    const i1 = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId }, 'SellerAR');
    const i1Id = getInvoiceId(i1);
    await addInvoiceLine(workspaceId, i1Id, { quantity_units: 1, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, i1Id, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${i1Id}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, i1Id, 'BuyerAP').then(expectSuccess);

    const i2 = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId }, 'SellerAR');
    const i2Id = getInvoiceId(i2);
    await addInvoiceLine(workspaceId, i2Id, { quantity_units: 1, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, i2Id, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${i2Id}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, i2Id, 'BuyerAP').then(expectSuccess);

    const cm = await createCreditMemo(workspaceId, customerId, { reason: 'GOODWILL', items: [{ quantity_units: 1, unit_price_cents: 5_000 }] }, 'SellerAR');
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAR');
    await applyCreditMemo(workspaceId, cmId, i1Id, 'SellerAR');

    const inv1 = await getInvoice(workspaceId, i1Id, 'SellerAdmin');
    const inv2 = await getInvoice(workspaceId, i2Id, 'SellerAdmin');
    expect(inv1.amount_due_cents).toBe(5_000);
    expect(inv2.amount_due_cents).toBe(10_000);

    const payment = await createPayment(
      workspaceId,
      customerId,
      {
        amount_cents: 20_000,
        allocations: [
          { invoice_id: i1Id, amount_cents: 5_000 },
          { invoice_id: i2Id, amount_cents: 10_000 }
        ]
      },
      'BuyerAP'
    );
    const paymentId = getPaymentId(payment);
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const custAfterClear = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custAfterClear.unapplied_cash_cents).toBe(5_000);

    await reversePayment(workspaceId, paymentId, 'SellerAdmin').then(expectSuccess);

    const custAfterReverse = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custAfterReverse.status).toBe('FROZEN');
    expect(custAfterReverse.unapplied_cash_cents).toBe(0);

    const inv1Restored = await getInvoice(workspaceId, i1Id, 'SellerAdmin');
    const inv2Restored = await getInvoice(workspaceId, i2Id, 'SellerAdmin');
    expect(inv1Restored.amount_due_cents).toBe(5_000);
    expect(inv2Restored.amount_due_cents).toBe(10_000);
  });

  test('DEEP_009: after books closed, must correct via credits; recompute yields CLOSED invoice when fully credited', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: false, payment_terms_periods: 2 });

    const po = await createPurchaseOrder(workspaceId, customerId, { lines: [{ ordered_units: 1, unit_price_cents: 10_000, is_service: true }] }, 'BuyerAP');
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 1, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');

    await advancePeriod(workspaceId, 'System');
    await closeBooks(workspaceId, 'Auditor').then(expectSuccess);

    const voidRes = await voidInvoice(workspaceId, invoiceId, 'SellerAR');
    await expectErrorCode(voidRes, 'ERR_BOOKS_CLOSED');

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
    await applyCreditMemo(workspaceId, cmId, invoiceId, 'SellerAR');

    const recomputeRes = await recompute(workspaceId, 'SellerAdmin');
    expectSuccess(recomputeRes);

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('CLOSED');
    expect(inv.amount_due_cents).toBe(0);
  });

  test('DEEP_010: deemed acceptance happens only after match exception is resolved and next period closes', async () => {
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

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 10_600, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.status).toBe('SENT');
    expect(inv0.match_status).toBe('EXCEPTION');

    await advancePeriod(workspaceId, 'System');
    const inv1 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv1.status).toBe('SENT');

    const lineId = getFirstInvoiceLineId(inv1);
    const cm = await createCreditMemo(
      workspaceId,
      customerId,
      { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: lineId, quantity_units: 10, unit_price_cents: 100 }] },
      'SellerAR'
    );
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAR');
    await applyCreditMemo(workspaceId, cmId, invoiceId, 'SellerAR');

    const invMatched = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invMatched.match_status).toBe('MATCHED');
    expect(invMatched.status).toBe('SENT');

    await advancePeriod(workspaceId, 'System');
    const invAccepted = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAccepted.status).toBe('ACCEPTED');
    expect(invAccepted.accepted_period_index).toBe(1);
    expect(invAccepted.due_period_index).toBe(invAccepted.accepted_period_index + 1);
  });

  test('DEEP_014: reversal-based freeze window anchors to most recent reversal and can auto-unfreeze after two advances', async () => {
    const ws = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
    const workspaceId = ws.workspace_id;
    const customer = await createCustomer(workspaceId, {}, 'SellerAdmin');
    const customerId = getCustomerId(customer);

    const p1 = await createPayment(workspaceId, customerId, { amount_cents: 10_000 }, 'BuyerAP');
    const p1Id = getPaymentId(p1);
    await markPaymentCleared(workspaceId, p1Id, 'SellerAR');
    await reversePayment(workspaceId, p1Id, 'SellerAdmin').then(expectSuccess);

    const afterP1 = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(afterP1.status).toBe('FROZEN');
    expect(afterP1.unapplied_cash_cents).toBe(0);

    await advancePeriod(workspaceId, 'System');

    const p2 = await createPayment(workspaceId, customerId, { amount_cents: 5_000 }, 'SellerAR');
    const p2Id = getPaymentId(p2);
    await markPaymentCleared(workspaceId, p2Id, 'SellerAR');
    await reversePayment(workspaceId, p2Id, 'SellerAdmin').then(expectSuccess);

    await advancePeriod(workspaceId, 'System');

    const pre = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(pre.status).toBe('FROZEN');
    expect(pre.unapplied_cash_cents).toBe(0);

    await advancePeriod(workspaceId, 'System');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('ACTIVE');
    expect(cust.balance_due_cents).toBe(0);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);

    const pay1 = await getPayment(workspaceId, p1Id, 'SellerAdmin');
    const pay2 = await getPayment(workspaceId, p2Id, 'SellerAdmin');
    expect(pay1.status).toBe('REVERSED');
    expect(pay2.status).toBe('REVERSED');
  });

  test('DEEP_015: partial receipt allows partial payment while SENT; later receipts enable deemed acceptance without changing remaining due', async () => {
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

    await postAs(`/workspaces/${workspaceId}/purchase_orders/${poId}/record_receipt`, { items: [{ purchase_order_line_id: poLineId, received_units: 5 }] }, 'BuyerAP').then(
      expectSuccess
    );

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);

    const sent0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(sent0.status).toBe('SENT');
    expect(sent0.match_status).toBe('EXCEPTION');

    const payment = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 50_000, allocations: [{ invoice_id: invoiceId, amount_cents: 50_000 }] },
      'BuyerAP'
    );
    await markPaymentCleared(workspaceId, getPaymentId(payment), 'SellerAR');

    const afterPay = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(afterPay.status).toBe('SENT');
    expect(afterPay.amount_due_cents).toBe(50_000);

    await advancePeriod(workspaceId, 'System');

    await postAs(`/workspaces/${workspaceId}/purchase_orders/${poId}/record_receipt`, { items: [{ purchase_order_line_id: poLineId, received_units: 5 }] }, 'BuyerAP').then(
      expectSuccess
    );

    const matched = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(matched.status).toBe('SENT');
    expect(matched.match_status).toBe('MATCHED');

    await advancePeriod(workspaceId, 'System');

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('ACCEPTED');
    expect(inv.accepted_period_index).toBe(1);
    expect(inv.due_period_index).toBe(3);
    expect(inv.delivered_period_index).toBe(0);
    expect(inv.amount_due_cents).toBe(50_000);
    expect(inv.amount_disputed_cents).toBe(0);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(50_000);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);
  });

  test('DEEP_016: auto-withdraw PROPOSED dispute voids draft credit and enables deemed acceptance in same period close', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: true, payment_terms_periods: 1 });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 10, unit_price_cents: 1_000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 1_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.status).toBe('SENT');
    expect(inv0.delivered_period_index).toBe(0);
    expect(inv0.match_status).toBe('MATCHED');
    expect(inv0.amount_due_cents).toBe(10_000);
    const lineId = getFirstInvoiceLineId(inv0);

    const dispute = await createDispute(
      workspaceId,
      invoiceId,
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

    const d0 = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(d0.status).toBe('PROPOSED');

    const cms = await listCreditMemos(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const arr = Array.isArray(cms) ? cms : (cms as any[]) ?? [];
    const draft = (arr as any[]).find((cm) => cm.status === 'DRAFT');
    if (!draft) throw new Error('Expected a DRAFT credit memo from propose_resolution');
    const cmId = getCreditMemoId(draft);

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');
    const stillProposed = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(stillProposed.status).toBe('PROPOSED');

    await advancePeriod(workspaceId, 'System');
    const w = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(w.period_index).toBe(3);

    const d1 = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(d1.status).toBe('WITHDRAWN');

    const cm = await getCreditMemo(workspaceId, cmId, 'SellerAdmin');
    expect(cm.status).toBe('VOIDED');

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('ACCEPTED');
    expect(inv.accepted_period_index).toBe(2);
    expect(inv.due_period_index).toBe(3);
    expect(inv.delivered_period_index).toBe(0);
    expect(inv.match_status).toBe('MATCHED');
    expect(inv.amount_disputed_cents).toBe(0);
    expect(inv.amount_due_cents).toBe(10_000);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(10_000);
    expect(inv.due_period_index).toBe((inv.accepted_period_index as number) + 1);
  });

  test('DEEP_017: write_off clears COLLECTIONS and unblocks new invoice finalization', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: false, payment_terms_periods: 1 });

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `D17-${workspaceId}` }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 15, unit_price_cents: 1_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    await advanceToPeriod(workspaceId, 4);
    const invColl = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invColl.collections_stage).toBe('COLLECTIONS');

    const writeOffRes = await writeOffInvoice(workspaceId, invoiceId, 'SellerAR');
    expectSuccess(writeOffRes);

    const i2 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `D17-NEW-${workspaceId}` }, 'SellerAR');
    const i2Id = getInvoiceId(i2);
    await addInvoiceLine(workspaceId, i2Id, { quantity_units: 5, unit_price_cents: 1_000 }, 'SellerAR');

    const finRes = await postAs(
      `/workspaces/${workspaceId}/invoices/${i2Id}/finalize`,
      { override_hold: false, override_billing_cap: false, final_invoice: false },
      'SellerAR'
    );
    expectSuccess(finRes);

    const inv2 = await getInvoice(workspaceId, i2Id, 'SellerAdmin');
    expect(inv2.status).toBe('FINALIZED');
    expect(inv2.issued_period_index).toBe(4);
    expect(inv2.invoice_total_cents).toBe(5_000);
    expect(inv2.amount_due_cents).toBe(5_000);

    const invWrittenOff = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invWrittenOff.status).toBe('CLOSED');
    expect(invWrittenOff.amount_due_cents).toBe(0);
    expect(invWrittenOff.collections_stage).toBe('CURRENT');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('ACTIVE');

    expect(cust.balance_due_cents).toBe(10_000);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);

    const invs = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    expect(invs.some((i: any) => i.collections_stage === 'COLLECTIONS')).toBe(false);
  });

  test('DEEP_018: newer FRAUD dispute resets freeze cooling-off; unfreeze fails with ERR_CUSTOMER_STILL_FROZEN', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: false, payment_terms_periods: 1 });

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `D18-${workspaceId}` }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const lineId = getFirstInvoiceLineId(inv0);
    const d1 = await createDispute(workspaceId, invoiceId, { reason: 'FRAUD', items: [{ invoice_line_id: lineId, disputed_amount_cents: 10_000 }] }, 'BuyerAP');
    const d1Id = getDisputeId(d1);
    await withdrawDispute(workspaceId, d1Id, 'BuyerAP');

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');
    const active = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(active.status).toBe('ACTIVE');

    const d2 = await createDispute(workspaceId, invoiceId, { reason: 'FRAUD', items: [{ invoice_line_id: lineId, disputed_amount_cents: 10_000 }] }, 'BuyerAP');
    const d2Id = getDisputeId(d2);
    await withdrawDispute(workspaceId, d2Id, 'BuyerAP');

    await advancePeriod(workspaceId, 'System');
    const frozen = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(frozen.status).toBe('FROZEN');

    const res = await unfreezeCustomer(workspaceId, customerId, 'SellerAdmin');
    await expectErrorCode(res, 'ERR_CUSTOMER_STILL_FROZEN');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('FROZEN');

    const gd1 = await getDispute(workspaceId, d1Id, 'SellerAdmin');
    const gd2 = await getDispute(workspaceId, d2Id, 'SellerAdmin');
    expect(gd1.status).toBe('WITHDRAWN');
    expect(gd2.status).toBe('WITHDRAWN');
  });

  test('DEEP_020: clearing an INITIATED payment after invoice is written off yields unapplied cash', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: false, payment_terms_periods: 1 });

    const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `D20-${workspaceId}` }, 'SellerAR');
    const invoiceId = getInvoiceId(inv);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 15, unit_price_cents: 1_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    await advanceToPeriod(workspaceId, 4);
    const invColl = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invColl.collections_stage).toBe('COLLECTIONS');

    const p = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 15_000, allocations: [{ invoice_id: invoiceId, amount_cents: 15_000 }] },
      'BuyerAP'
    );
    const paymentId = getPaymentId(p);
    const pay0 = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(pay0.status).toBe('INITIATED');

    const writeOffRes = await writeOffInvoice(workspaceId, invoiceId, 'SellerAR');
    expectSuccess(writeOffRes);
    const invClosed = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invClosed.status).toBe('CLOSED');
    expect(invClosed.amount_due_cents).toBe(0);

    const snap = await getCustomer(workspaceId, customerId, 'SellerAdmin');

    expect(snap.balance_due_cents).toBe(5_000);
    expect(snap.unapplied_cash_cents).toBe(0);

    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');
    const pay = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(pay.status).toBe('CLEARED');

    const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter.status).toBe('CLOSED');
    expect(invAfter.amount_due_cents).toBe(0);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(5_000);
    expect(cust.unapplied_cash_cents).toBe(15_000);
    expect(cust.available_credit_cents).toBe(0);

    const invs = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const sumDue = (invs as any[]).filter((i) => i.status !== 'DRAFT' && i.status !== 'VOIDED').reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
    expect(sumDue).toBe(5_000);
  });

  test('DEEP_021: clearing payment with match exception (missing receipts) pays only matchable portion; remainder becomes unapplied cash', async () => {
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

    const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId }, 'SellerAR');
    const invoiceId = getInvoiceId(inv);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.status).toBe('SENT');
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

    await withdrawDispute(workspaceId, disputeId, 'BuyerAP');
    const invAfterWithdraw = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfterWithdraw.amount_disputed_cents).toBe(0);
    expect(invAfterWithdraw.match_status).toBe('EXCEPTION');

    const pmt = await createPayment(workspaceId, customerId, { amount_cents: 100_000 }, 'BuyerAP');
    const paymentId = getPaymentId(pmt);
    const snap = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(snap.balance_due_cents).toBe(100_000);
    expect(snap.unapplied_cash_cents).toBe(0);

    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const pay = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(pay.status).toBe('CLEARED');

    const invFinal = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invFinal.status).toBe('ACCEPTED');
    expect(invFinal.amount_due_cents).toBe(50_000);
    expect(invFinal.amount_disputed_cents).toBe(0);
    expect(invFinal.match_status).toBe('EXCEPTION');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(50_000);
    expect(cust.unapplied_cash_cents).toBe(50_000);
    expect(cust.available_credit_cents).toBe(0);
    expect(cust.balance_due_cents).toBe(invFinal.amount_due_cents);
  });

  test('DEEP_022: applying credit can change PO quantity match by reducing net_billed_units', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: true, payment_terms_periods: 2 });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 100, unit_price_cents: 10_000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    const i1 = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId }, 'SellerAR');
    const i1Id = getInvoiceId(i1);
    await addInvoiceLine(workspaceId, i1Id, { quantity_units: 100, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, i1Id, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${i1Id}/send`, {}, 'SellerAR').then(expectSuccess);

    const i2 = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId }, 'SellerAR');
    const i2Id = getInvoiceId(i2);
    await addInvoiceLine(workspaceId, i2Id, { quantity_units: 3, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, i2Id, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${i2Id}/send`, {}, 'SellerAR').then(expectSuccess);

    const poBefore = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    expect(poBefore.lines[0].net_billed_units).toBe(103);

    const inv2Before = await getInvoice(workspaceId, i2Id, 'SellerAdmin');
    expect(inv2Before.match_status).toBe('EXCEPTION');
    const il2 = getFirstInvoiceLineId(inv2Before);

    const cm = await createCreditMemo(
      workspaceId,
      customerId,
      { invoice_id: i2Id, reason: 'GOODWILL', items: [{ invoice_line_id: il2, quantity_units: 1, unit_price_cents: 10_000 }] },
      'SellerAR'
    );
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAR');

    await applyCreditMemo(workspaceId, cmId, i2Id, 'SellerAR');

    const poAfter = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    expect(poAfter.lines[0].net_billed_units).toBe(102);

    const inv2After = await getInvoice(workspaceId, i2Id, 'SellerAdmin');
    expect(inv2After.match_status).toBe('MATCHED');
    expect(inv2After.amount_due_cents).toBe(20_000);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(1_020_000);
    expect(cust.available_credit_cents).toBe(0);
  });

  test('DEEP_023: credit on undisputed line can make invoice fully disputed and reset collections_stage to CURRENT', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: false, payment_terms_periods: 1 });

    const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `D23-${workspaceId}` }, 'SellerAR');
    const invoiceId = getInvoiceId(inv);
    await addInvoiceLine(workspaceId, invoiceId, { description: 'L1', quantity_units: 1, unit_price_cents: 40_000 }, 'SellerAR');
    await addInvoiceLine(workspaceId, invoiceId, { description: 'L2', quantity_units: 1, unit_price_cents: 60_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.amount_due_cents).toBe(100_000);
    const line1 = getFirstInvoiceLineId(inv0);
    const line2 = (inv0.lines?.[1]?.invoice_line_id ?? inv0.lines?.[1]?.id) as string;
    if (!line2) throw new Error('Could not resolve second invoice line id');

    await createDispute(workspaceId, invoiceId, { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: line1, disputed_amount_cents: 40_000 }] }, 'BuyerAP');
    await advanceToCollections(workspaceId, invoiceId);

    const invColl = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invColl.collections_stage).toBe('COLLECTIONS');

    const cm = await createCreditMemo(
      workspaceId,
      customerId,
      { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: line2, quantity_units: 1, unit_price_cents: 60_000 }] },
      'SellerAR'
    );
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAR');
    await applyCreditMemo(workspaceId, cmId, invoiceId, 'SellerAR');

    const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter.status).toBe('ACCEPTED');
    expect(invAfter.amount_due_cents).toBe(40_000);
    expect(invAfter.amount_disputed_cents).toBe(40_000);
    expect(invAfter.collections_stage).toBe('CURRENT');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(45_000);
    expect(cust.available_credit_cents).toBe(0);
  });

  test('DEEP_024: active dispute blocks deemed acceptance; advance_period escalates OPEN dispute and puts customer on CREDIT_HOLD', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: true, payment_terms_periods: 1 });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 1, unit_price_cents: 10_000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const poLineId = getFirstPurchaseOrderLineId(poFull);

    const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId }, 'SellerAR');
    const invoiceId = getInvoiceId(inv);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 1, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);

    const sent = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(sent.status).toBe('SENT');
    expect(sent.delivered_period_index).toBe(0);
    expect(sent.match_status).toBe('MATCHED');
    const lineId = getFirstInvoiceLineId(sent);

    const dispute = await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: 5_000 }] },
      'BuyerAP'
    );
    const disputeId = getDisputeId(dispute);

    await advancePeriod(workspaceId, 'System');
    const pre = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(pre.status).toBe('SENT');
    expect(pre.accepted_period_index == null).toBe(true);

    await advancePeriod(workspaceId, 'System');
    const w = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(w.period_index).toBe(2);

    const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter.status).toBe('SENT');
    expect(invAfter.accepted_period_index == null).toBe(true);
    expect(invAfter.due_period_index == null).toBe(true);

    const d = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(d.status).toBe('ESCALATED');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('CREDIT_HOLD');
  });

  test('DEEP_025: early-pay discount can apply after dispute is opened+withdrawn before clearing', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: false, payment_terms_periods: 2 });

    const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `D25-${workspaceId}` }, 'SellerAR');
    const invoiceId = getInvoiceId(inv);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.accepted_period_index).toBe(0);
    expect(inv0.due_period_index).toBe(2);
    const lineId = getFirstInvoiceLineId(inv0);

    const p = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 98_000, allocations: [{ invoice_id: invoiceId, amount_cents: 98_000 }] },
      'BuyerAP'
    );
    const paymentId = getPaymentId(p);

    const dispute = await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: 10_000 }] },
      'BuyerAP'
    );
    const disputeId = getDisputeId(dispute);
    await withdrawDispute(workspaceId, disputeId, 'BuyerAP');

    await advancePeriod(workspaceId, 'System');

    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const pay = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(pay.status).toBe('CLEARED');

    const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter.status).toBe('CLOSED');
    expect(invAfter.amount_due_cents).toBe(0);
    expect(invAfter.amount_disputed_cents).toBe(0);

    const epd = (await listCreditMemos(workspaceId, { customer_id: customerId }, 'SellerAdmin')).find((cm: any) => {
      const t = cm?.type ?? cm?.credit_memo_type ?? cm?.reason;
      return t === 'EARLY_PAY_DISCOUNT';
    });
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

    const d = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(d.status).toBe('WITHDRAWN');
  });

  test('DEEP_026: auto-allocation continues to next invoice when oldest is only partially payable due to receipt limits', async () => {
    const ws = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
    const workspaceId = ws.workspace_id;
    const customer = await createCustomer(workspaceId, {}, 'SellerAdmin');
    const customerId = getCustomerId(customer);

    const kPo = await createContract(
      workspaceId,
      customerId,
      { name: `K-PO`, requires_po: true, payment_terms_periods: 1, billing_cap_cents_per_period: 10_000_000 },
      'SellerAdmin'
    );
    const kPoId = kPo.contract_id ?? kPo.id;
    await activateContract(workspaceId, kPoId, 'SellerAdmin');

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

    const i1 = await createInvoice(workspaceId, customerId, { contract_id: kPoId, purchase_order_id: poId, external_invoice_ref: `D26-I1-${workspaceId}` }, 'SellerAR');
    const i1Id = getInvoiceId(i1);
    await addInvoiceLine(workspaceId, i1Id, { quantity_units: 10, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, i1Id, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${i1Id}/send`, {}, 'SellerAR').then(expectSuccess);

    const i1Sent = await getInvoice(workspaceId, i1Id, 'SellerAdmin');
    const i1LineId = getFirstInvoiceLineId(i1Sent);

    const dispute = await createDispute(
      workspaceId,
      i1Id,
      { reason: 'MISSING_RECEIPT', items: [{ invoice_line_id: i1LineId, disputed_units: 5 }] },
      'BuyerAP'
    );
    const disputeId = getDisputeId(dispute);
    await acceptInvoice(workspaceId, i1Id, 'BuyerAP').then(expectSuccess);
    await withdrawDispute(workspaceId, disputeId, 'BuyerAP');

    const i1AfterWithdraw = await getInvoice(workspaceId, i1Id, 'SellerAdmin');
    expect(i1AfterWithdraw.amount_disputed_cents).toBe(0);
    expect(i1AfterWithdraw.match_status).toBe('EXCEPTION');
    expect(i1AfterWithdraw.due_period_index).toBe(1);

    await advancePeriod(workspaceId, 'System');

    const kNa = await createContract(
      workspaceId,
      customerId,
      { name: `K-NA`, requires_po: false, payment_terms_periods: 1, billing_cap_cents_per_period: 10_000_000 },
      'SellerAdmin'
    );
    const kNaId = kNa.contract_id ?? kNa.id;
    await activateContract(workspaceId, kNaId, 'SellerAdmin');

    const i2 = await createInvoice(workspaceId, customerId, { contract_id: kNaId, external_invoice_ref: `D26-I2-${workspaceId}` }, 'SellerAR');
    const i2Id = getInvoiceId(i2);
    await addInvoiceLine(workspaceId, i2Id, { quantity_units: 6, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, i2Id, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${i2Id}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, i2Id, 'BuyerAP').then(expectSuccess);

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');
    const ws3 = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(ws3.period_index).toBe(3);

    const pmt = await createPayment(workspaceId, customerId, { amount_cents: 100_000 }, 'BuyerAP');
    const paymentId = getPaymentId(pmt);
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const pay = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(pay.status).toBe('CLEARED');

    const inv1 = await getInvoice(workspaceId, i1Id, 'SellerAdmin');
    expect(inv1.status).toBe('ACCEPTED');
    expect(inv1.amount_due_cents).toBe(50_000);
    expect(inv1.amount_disputed_cents).toBe(0);
    expect(inv1.match_status).toBe('EXCEPTION');

    const inv2 = await getInvoice(workspaceId, i2Id, 'SellerAdmin');
    expect(inv2.status).toBe('ACCEPTED');
    expect(inv2.amount_due_cents).toBe(10_000);
    expect(inv2.amount_disputed_cents).toBe(0);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');

    expect(cust.balance_due_cents).toBe(62_500);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);

    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const sumDue = all
      .filter((inv: any) => inv.status !== 'DRAFT' && inv.status !== 'VOIDED')
      .reduce((acc: number, inv: any) => acc + (inv.amount_due_cents as number), 0);
    expect(sumDue).toBe(62_500);
    expect(sumDue).toBe(cust.balance_due_cents);
  });

  test('DEEP_027: finance charges resume after a payment reversal restores overdue balance', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: false, payment_terms_periods: 1 });

    const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `D27-${workspaceId}` }, 'SellerAR');
    const invoiceId = getInvoiceId(inv);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const adv = await advancePeriod(workspaceId, 'System');
    const financeIds = (adv as any).finance_charge_invoice_ids as string[] | undefined;
    expect(Array.isArray(financeIds)).toBe(true);
    expect(financeIds?.length).toBe(1);
    const f1 = financeIds![0];

    const f1Inv = await getInvoice(workspaceId, f1, 'SellerAdmin');
    expect(f1Inv.type).toBe('FINANCE_CHARGE');
    expect(f1Inv.status).toBe('ACCEPTED');
    expect(f1Inv.issued_period_index).toBe(3);
    expect(f1Inv.invoice_total_cents).toBe(2_500);

    const p = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 100_000, allocations: [{ invoice_id: invoiceId, amount_cents: 100_000 }] },
      'BuyerAP'
    );
    const paymentId = getPaymentId(p);
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const invClosed = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invClosed.status).toBe('CLOSED');

    await reversePayment(workspaceId, paymentId, 'SellerAdmin').then(expectSuccess);
    const payRev = await getPayment(workspaceId, paymentId, 'SellerAdmin');
    expect(payRev.status).toBe('REVERSED');

    const invReopen = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invReopen.status).toBe('ACCEPTED');
    expect(invReopen.amount_due_cents).toBe(100_000);

    const snap = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(snap.status).toBe('FROZEN');
    const bBefore = snap.balance_due_cents as number;

    const out = await advancePeriod(workspaceId, 'System');
    const f2Ids = (out as any).finance_charge_invoice_ids as string[] | undefined;
    expect((out as any).period_index).toBe(4);
    expect(Array.isArray(f2Ids)).toBe(true);
    expect(f2Ids?.length).toBe(1);
    const f2 = f2Ids![0];
    expect(f2).not.toBe(f1);

    const f2Inv = await getInvoice(workspaceId, f2, 'SellerAdmin');
    expect(f2Inv.type).toBe('FINANCE_CHARGE');
    expect(f2Inv.status).toBe('ACCEPTED');
    expect(f2Inv.issued_period_index).toBe(4);
    expect(f2Inv.delivered_period_index).toBe(4);
    expect(f2Inv.accepted_period_index).toBe(4);
    expect(f2Inv.due_period_index).toBe(5);
    expect(f2Inv.invoice_total_cents).toBe(2_500);
    expect(f2Inv.amount_due_cents).toBe(2_500);

    const charges = await listInvoices(workspaceId, { customer_id: customerId, type: 'FINANCE_CHARGE' }, 'SellerAdmin');
    expect(charges).toHaveLength(2);
    const chargeIds = charges.map((i: any) => getInvoiceId(i)).sort();
    expect(chargeIds).toEqual([f1, f2].sort());

    const custAfter = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custAfter.status).toBe('FROZEN');
    expect(custAfter.balance_due_cents).toBe(bBefore + 2_500);

    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const sumDue = all
      .filter((inv: any) => inv.status !== 'DRAFT' && inv.status !== 'VOIDED')
      .reduce((acc: number, inv: any) => acc + (inv.amount_due_cents as number), 0);
    expect(sumDue).toBe(custAfter.balance_due_cents);
  });

  test('DEEP_028: dispute resolution (accept_resolution) works after close_books and settles invoice via credit', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: false, payment_terms_periods: 1 });

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `D28-${workspaceId}` }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
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

    const dProposed = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(dProposed.status).toBe('PROPOSED');

    const cms = await listCreditMemos(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const arr = Array.isArray(cms) ? cms : (cms as any[]) ?? [];
    const draft = (arr as any[]).find((cm) => cm.status === 'DRAFT');
    if (!draft) throw new Error('Expected a DRAFT credit memo from propose_resolution');
    const creditMemoId = getCreditMemoId(draft);

    await advancePeriod(workspaceId, 'System');

    await closeBooks(workspaceId, 'Auditor').then(expectSuccess);
    const ws = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(ws.period_index).toBe(1);
    expect(ws.books_closed_through_period_index).toBe(0);

    const acc = await acceptResolution(workspaceId, disputeId, 'BuyerAP');
    expectSuccess(acc);

    const dClosed = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(dClosed.status).toBe('CLOSED');

    const cm = await getCreditMemo(workspaceId, creditMemoId, 'SellerAdmin');
    expect(cm.status).toBe('ISSUED');

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('CLOSED');
    expect(inv.amount_due_cents).toBe(0);
    expect(inv.amount_disputed_cents).toBe(0);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);
    expect(cust.unapplied_cash_cents).toBe(0);

    const wsAfter = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(wsAfter.period_index).toBe(1);
    expect(wsAfter.books_closed_through_period_index).toBe(0);

    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const sumDue = all
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((acc: number, i: any) => acc + (i.amount_due_cents as number), 0);
    expect(sumDue).toBe(0);
    expect(sumDue).toBe(cust.balance_due_cents);
  });

  test('DEEP_029: PROPOSED FRAUD dispute auto-withdraws, voids draft credit, and customer unfreezes after 2 period closes since withdraw', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: false, payment_terms_periods: 10 });

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `D29-${workspaceId}` }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.accepted_period_index).toBe(0);
    expect(inv0.due_period_index).toBe(10);
    const lineId = getFirstInvoiceLineId(inv0);

    const dispute = await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'FRAUD', items: [{ invoice_line_id: lineId, disputed_amount_cents: 10_000 }] },
      'BuyerAP'
    );
    const disputeId = getDisputeId(dispute);

    const custFrozen = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custFrozen.status).toBe('FROZEN');

    await proposeResolution(
      workspaceId,
      disputeId,
      { proposed_credit: { items: [{ invoice_line_id: lineId, quantity_units: 1, unit_price_cents: 10_000 }] } },
      'SellerAdmin'
    );
    const dProposed = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(dProposed.status).toBe('PROPOSED');

    const cms = await listCreditMemos(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const arr = Array.isArray(cms) ? cms : (cms as any[]) ?? [];
    const draft = (arr as any[]).find((cm) => cm.status === 'DRAFT');
    if (!draft) throw new Error('Expected a DRAFT credit memo from propose_resolution');
    const cmId = getCreditMemoId(draft);

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const w3 = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(w3.period_index).toBe(3);

    const dWithdrawn = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(dWithdrawn.status).toBe('WITHDRAWN');

    const cmVoided = await getCreditMemo(workspaceId, cmId, 'SellerAdmin');
    expect(cmVoided.status).toBe('VOIDED');

    const invAfterWithdraw = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfterWithdraw.status).toBe('ACCEPTED');
    expect(invAfterWithdraw.amount_due_cents).toBe(10_000);
    expect(invAfterWithdraw.amount_disputed_cents).toBe(0);
    expect(invAfterWithdraw.due_period_index).toBe(10);

    const custStillFrozen = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custStillFrozen.status).toBe('FROZEN');

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const w5 = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(w5.period_index).toBe(5);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('ACTIVE');
    expect(cust.balance_due_cents).toBe(10_000);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);

    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const sumDue = all
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((acc: number, i: any) => acc + (i.amount_due_cents as number), 0);
    expect(sumDue).toBe(10_000);
    expect(sumDue).toBe(cust.balance_due_cents);
  });

  test('DEEP_030: accept_resolution is idempotent (same Idempotency_Key does not double-issue/apply credit)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: false, payment_terms_periods: 1 });

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `D30-${workspaceId}` }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
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
    const dProposed = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(dProposed.status).toBe('PROPOSED');

    const cms = await listCreditMemos(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const arr = Array.isArray(cms) ? cms : (cms as any[]) ?? [];
    const draft = (arr as any[]).find((cm) => cm.status === 'DRAFT');
    if (!draft) throw new Error('Expected a DRAFT credit memo from propose_resolution');
    const cmId = getCreditMemoId(draft);

    const key = 'K_ACC';
    const r1 = await postAs(`/workspaces/${workspaceId}/disputes/${disputeId}/accept_resolution`, {}, 'BuyerAP', { Idempotency_Key: key });
    expectSuccess(r1);
    const r2 = await postAs(`/workspaces/${workspaceId}/disputes/${disputeId}/accept_resolution`, {}, 'BuyerAP', { Idempotency_Key: key });
    expectSuccess(r2);
    expect(r2.body).toEqual(r1.body);

    const dClosed = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(dClosed.status).toBe('CLOSED');

    const cm = await getCreditMemo(workspaceId, cmId, 'SellerAdmin');
    expect(cm.status).toBe('ISSUED');

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('CLOSED');
    expect(inv.amount_due_cents).toBe(0);
    expect(inv.amount_disputed_cents).toBe(0);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);
    expect(cust.unapplied_cash_cents).toBe(0);

    const issued = await listCreditMemos(workspaceId, { customer_id: customerId, status: 'ISSUED' }, 'SellerAdmin');
    const issuedArr = Array.isArray(issued) ? issued : (issued as any[]) ?? [];
    expect(issuedArr).toHaveLength(1);
    const onlyId = getCreditMemoId(issuedArr[0]);
    expect(onlyId).toBe(cmId);
  });

  test('DEEP_031: applying a unit credit can reduce net_billed_units to received_units and enable acceptance', async () => {
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

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 102, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.status).toBe('SENT');
    expect(inv0.match_status).toBe('EXCEPTION');
    expect(inv0.amount_due_cents).toBe(1_020_000);

    await recordReceipt(workspaceId, poId, [{ purchase_order_line_id: poLineId, received_units: 101 }], 'BuyerAP').then(expectSuccess);
    const invAfterReceipt = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfterReceipt.match_status).toBe('EXCEPTION');

    const invoiceLineId = getFirstInvoiceLineId(invAfterReceipt);
    const cm = await createCreditMemo(
      workspaceId,
      customerId,
      { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: invoiceLineId, quantity_units: 1, unit_price_cents: 10_000 }] },
      'SellerAR'
    );
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAR');
    await applyCreditMemo(workspaceId, cmId, invoiceId, 'SellerAR');

    const poAfter = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    expect(poAfter.lines[0].received_units).toBe(101);
    expect(poAfter.lines[0].net_billed_units).toBe(101);

    const invMatched = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invMatched.match_status).toBe('MATCHED');
    expect(invMatched.amount_due_cents).toBe(1_010_000);

    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const invAccepted = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAccepted.status).toBe('ACCEPTED');
    expect(invAccepted.delivered_period_index).toBe(0);
    expect(invAccepted.accepted_period_index).toBe(0);
    expect(invAccepted.due_period_index).toBe(1);
    expect(invAccepted.match_status).toBe('MATCHED');
    expect(invAccepted.amount_due_cents).toBe(1_010_000);
    expect(invAccepted.amount_disputed_cents).toBe(0);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(1_010_000);
    expect(cust.available_credit_cents).toBe(0);
    expect(cust.unapplied_cash_cents).toBe(0);

    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const sumDue = all
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((acc: number, i: any) => acc + (i.amount_due_cents as number), 0);
    expect(sumDue).toBe(1_010_000);
    expect(sumDue).toBe(cust.balance_due_cents);
  });

  test('DEEP_032: an overdue FINANCE_CHARGE invoice can itself generate a finance charge invoice', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: false, payment_terms_periods: 1 });

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `D32-${workspaceId}` }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const out1 = await advancePeriod(workspaceId, 'System');
    const f1Ids = (out1 as any).finance_charge_invoice_ids as string[] | undefined;
    expect(Array.isArray(f1Ids)).toBe(true);
    expect(f1Ids?.length).toBe(1);
    const f1 = f1Ids![0];

    const fin1 = await getInvoice(workspaceId, f1, 'SellerAdmin');
    expect(fin1.type).toBe('FINANCE_CHARGE');
    expect(fin1.status).toBe('ACCEPTED');
    expect(fin1.issued_period_index).toBe(3);
    expect(fin1.due_period_index).toBe(4);
    expect(fin1.invoice_total_cents).toBe(2_500);
    expect(fin1.amount_due_cents).toBe(2_500);
    expect(fin1.reference_invoice_id).toBe(invoiceId);

    const pay = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 100_000, allocations: [{ invoice_id: invoiceId, amount_cents: 100_000 }] },
      'BuyerAP'
    );
    await markPaymentCleared(workspaceId, getPaymentId(pay), 'SellerAR');

    const invPaid = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invPaid.status).toBe('CLOSED');
    expect(invPaid.amount_due_cents).toBe(0);

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');
    const fin1Still = await getInvoice(workspaceId, f1, 'SellerAdmin');
    expect(fin1Still.status).toBe('ACCEPTED');
    expect(fin1Still.amount_due_cents).toBe(2_500);
    expect(fin1Still.due_period_index).toBe(4);

    const out2 = await advancePeriod(workspaceId, 'System');
    const f2Ids = (out2 as any).finance_charge_invoice_ids as string[] | undefined;
    expect(Array.isArray(f2Ids)).toBe(true);
    expect(f2Ids?.length).toBe(1);
    const f2 = f2Ids![0];
    expect(f2).not.toBe(f1);

    const ws = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(ws.period_index).toBe(6);

    const fin2 = await getInvoice(workspaceId, f2, 'SellerAdmin');
    expect(fin2.type).toBe('FINANCE_CHARGE');
    expect(fin2.status).toBe('ACCEPTED');
    expect(fin2.reference_invoice_id).toBe(f1);
    expect(fin2.issued_period_index).toBe(6);
    expect(fin2.delivered_period_index).toBe(6);
    expect(fin2.accepted_period_index).toBe(6);
    expect(fin2.due_period_index).toBe(7);
    expect(fin2.invoice_total_cents).toBe(2_500);
    expect(fin2.amount_due_cents).toBe(2_500);

    const invStillClosed = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invStillClosed.status).toBe('CLOSED');
    expect(invStillClosed.amount_due_cents).toBe(0);

    const fin1Final = await getInvoice(workspaceId, f1, 'SellerAdmin');
    expect(fin1Final.status).toBe('ACCEPTED');
    expect(fin1Final.amount_due_cents).toBe(2_500);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(5_000);

    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const sumDue = all
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((acc: number, i: any) => acc + (i.amount_due_cents as number), 0);
    expect(sumDue).toBe(5_000);
    expect(sumDue).toBe(cust.balance_due_cents);

    const charges = await listInvoices(workspaceId, { customer_id: customerId, type: 'FINANCE_CHARGE' }, 'SellerAdmin');
    expect(charges).toHaveLength(2);
    const ids = charges.map((i: any) => getInvoiceId(i)).sort();
    expect(ids).toEqual([f1, f2].sort());
  });

  test('DEEP_033: finance-charge invoice can age into COLLECTIONS and block new invoice finalization (ERR_CUSTOMER_ON_HOLD)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: false, payment_terms_periods: 1 });

    const orig = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `D33-${workspaceId}` }, 'SellerAR');
    const origId = getInvoiceId(orig);
    await addInvoiceLine(workspaceId, origId, { quantity_units: 10, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, origId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${origId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, origId, 'BuyerAP').then(expectSuccess);

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');
    const out = await advancePeriod(workspaceId, 'System');
    const financeIds = (out as any).finance_charge_invoice_ids as string[] | undefined;
    expect(Array.isArray(financeIds)).toBe(true);
    expect(financeIds?.length).toBe(1);
    const f1 = financeIds![0];

    const fin1 = await getInvoice(workspaceId, f1, 'SellerAdmin');
    expect(fin1.type).toBe('FINANCE_CHARGE');
    expect(fin1.status).toBe('ACCEPTED');
    expect(fin1.reference_invoice_id).toBe(origId);
    expect(fin1.issued_period_index).toBe(3);
    expect(fin1.due_period_index).toBe(4);
    expect(fin1.amount_due_cents).toBe(2_500);

    const pay = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 100_000, allocations: [{ invoice_id: origId, amount_cents: 100_000 }] },
      'BuyerAP'
    );
    await markPaymentCleared(workspaceId, getPaymentId(pay), 'SellerAR');
    const origClosed = await getInvoice(workspaceId, origId, 'SellerAdmin');
    expect(origClosed.status).toBe('CLOSED');
    expect(origClosed.amount_due_cents).toBe(0);

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const iNew = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `D33-NEW-${workspaceId}` }, 'SellerAR');
    const iNewId = getInvoiceId(iNew);
    await addInvoiceLine(workspaceId, iNewId, { quantity_units: 5, unit_price_cents: 1_000 }, 'SellerAR');

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${iNewId}/finalize`,
      { override_hold: false, override_billing_cap: false, final_invoice: false },
      'SellerAR'
    );
    await expectErrorCode(res, 'ERR_CUSTOMER_ON_HOLD');

    const invNew = await getInvoice(workspaceId, iNewId, 'SellerAdmin');
    expect(invNew.status).toBe('DRAFT');
    expect(invNew.invoice_total_cents).toBe(0);
    expect(invNew.issued_period_index == null).toBe(true);

    const charges = await listInvoices(workspaceId, { customer_id: customerId, type: 'FINANCE_CHARGE' }, 'SellerAdmin');
    expect(charges).toHaveLength(3);

    const full = await Promise.all(charges.map((c: any) => getInvoice(workspaceId, getInvoiceId(c), 'SellerAdmin')));
    expect(full.every((f) => f.type === 'FINANCE_CHARGE')).toBe(true);
    expect(full.every((f) => f.status === 'ACCEPTED')).toBe(true);
    expect(full.every((f) => f.amount_due_cents === f.invoice_total_cents)).toBe(true);
    expect(full.every((f) => f.amount_due_cents === 2_500)).toBe(true);

    const inCollections = full.filter((f) => f.collections_stage === 'COLLECTIONS');
    expect(inCollections).toHaveLength(1);
    expect(inCollections[0].reference_invoice_id).toBe(origId);
    expect(inCollections[0].amount_due_cents).toBe(2_500);
    expect(inCollections[0].due_period_index).toBe(4);

    const currents = full.filter((f) => f.collections_stage === 'CURRENT');
    expect(currents).toHaveLength(2);
    expect(currents.every((f) => f.amount_due_cents === 2_500)).toBe(true);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(7_500);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);

    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const sumDue = all
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((acc: number, i: any) => acc + (i.amount_due_cents as number), 0);
    expect(sumDue).toBe(7_500);
    expect(sumDue).toBe(cust.balance_due_cents);
  });

  test('DEEP_034: final true-up under SUSPENDED contract can be finalized with override_hold while customer is on CREDIT_HOLD', async () => {
    const { workspaceId, customerId, contractId: kHold } = await setupWorkspaceCustomerContract({ requires_po: false, payment_terms_periods: 1 });

    const iHold = await createInvoice(workspaceId, customerId, { contract_id: kHold, external_invoice_ref: `D34-HOLD-${uniqueId('inv')}` }, 'SellerAR');
    const iHoldId = getInvoiceId(iHold);
    await addInvoiceLine(workspaceId, iHoldId, { quantity_units: 260, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, iHoldId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${iHoldId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, iHoldId, 'BuyerAP').then(expectSuccess);

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const holdNow = await getInvoice(workspaceId, iHoldId, 'SellerAdmin');
    expect(holdNow.collections_stage).toBe('REMINDER');
    expect(holdNow.amount_due_cents).toBe(2_600_000);

    const custHold = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custHold.status).toBe('CREDIT_HOLD');

    const kSusp = await createContract(
      workspaceId,
      customerId,
      {
        name: `K-SUSP-${uniqueId('k')}`,
        requires_po: true,
        payment_terms_periods: 1,
        billing_cap_cents_per_period: 10_000_000
      },
      'SellerAdmin'
    );
    const kSuspId = kSusp.contract_id ?? kSusp.id;
    if (!kSuspId) throw new Error('Could not resolve contract_id');
    await activateContract(workspaceId, kSuspId, 'SellerAdmin');
    await postAs(`/workspaces/${workspaceId}/contracts/${kSuspId}/suspend`, {}, 'SellerAdmin').then(expectSuccess);

    const iTrueUp = await createInvoice(workspaceId, customerId, { contract_id: kSuspId, external_invoice_ref: `D34-TRUEUP-${uniqueId('inv')}` }, 'SellerAR');
    const iTrueUpId = getInvoiceId(iTrueUp);
    await addInvoiceLine(workspaceId, iTrueUpId, { quantity_units: 15, unit_price_cents: 10_000 }, 'SellerAR');

    const fin = await postAs(
      `/workspaces/${workspaceId}/invoices/${iTrueUpId}/finalize`,
      { override_hold: true, override_billing_cap: false, final_invoice: true },
      'SellerAdmin'
    );
    expectSuccess(fin);

    const invTrueUp = await getInvoice(workspaceId, iTrueUpId, 'SellerAdmin');
    expect(invTrueUp.status).toBe('FINALIZED');
    expect(invTrueUp.issued_period_index).toBe(2);
    expect(invTrueUp.purchase_order_id == null).toBe(true);
    expect(invTrueUp.match_status).toBe('NOT_APPLICABLE');
    expect(invTrueUp.invoice_total_cents).toBe(150_000);
    expect(invTrueUp.amount_due_cents).toBe(150_000);
    expect(invTrueUp.amount_disputed_cents).toBe(0);

    const holdAfter = await getInvoice(workspaceId, iHoldId, 'SellerAdmin');
    expect(holdAfter.status).toBe('ACCEPTED');
    expect(holdAfter.amount_due_cents).toBe(2_600_000);
    expect(holdAfter.amount_disputed_cents).toBe(0);
    expect(holdAfter.collections_stage).toBe('REMINDER');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('CREDIT_HOLD');
    expect(cust.balance_due_cents).toBe(2_750_000);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);

    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const sumDue = all
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((acc: number, i: any) => acc + (i.amount_due_cents as number), 0);
    expect(sumDue).toBe(2_750_000);
    expect(sumDue).toBe(cust.balance_due_cents);
  });

  test('DEEP_101: unfreeze fails if any REVERSED payment has fewer than 2 period closes since reversal (ERR_CUSTOMER_STILL_FROZEN)', async () => {
    const ws = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
    const workspaceId = ws.workspace_id;
    const customer = await createCustomer(workspaceId, {}, 'SellerAdmin');
    const customerId = getCustomerId(customer);

    const p1 = await createPayment(workspaceId, customerId, { amount_cents: 1_000 }, 'BuyerAP');
    const p1Id = getPaymentId(p1);
    await markPaymentCleared(workspaceId, p1Id, 'SellerAR');
    await reversePayment(workspaceId, p1Id, 'SellerAdmin').then(expectSuccess);

    await advancePeriod(workspaceId, 'System');

    const p2 = await createPayment(workspaceId, customerId, { amount_cents: 1_000 }, 'SellerAR');
    const p2Id = getPaymentId(p2);
    await markPaymentCleared(workspaceId, p2Id, 'SellerAR');
    await reversePayment(workspaceId, p2Id, 'SellerAdmin').then(expectSuccess);

    await advancePeriod(workspaceId, 'System');

    const cust0 = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust0.status).toBe('FROZEN');
    expect(cust0.balance_due_cents).toBe(0);
    expect(cust0.unapplied_cash_cents).toBe(0);
    expect(cust0.available_credit_cents).toBe(0);

    const res = await unfreezeCustomer(workspaceId, customerId, 'SellerAdmin');
    await expectErrorCode(res, 'ERR_CUSTOMER_STILL_FROZEN');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('FROZEN');
    expect(cust.balance_due_cents).toBe(0);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);

    const pay1 = await getPayment(workspaceId, p1Id, 'SellerAdmin');
    const pay2 = await getPayment(workspaceId, p2Id, 'SellerAdmin');
    expect(pay1.status).toBe('REVERSED');
    expect(pay2.status).toBe('REVERSED');
  });

  test('DEEP_102: once reversal freeze duration elapses, customer remains CREDIT_HOLD if there is an ESCALATED dispute', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: false, payment_terms_periods: 10 });

    const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `D102-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(inv);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 1_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const lineId = getFirstInvoiceLineId(inv0);
    const d = await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: 1_000 }] },
      'BuyerAP'
    );
    const disputeId = getDisputeId(d);

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const escalated = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(escalated.status).toBe('ESCALATED');
    const custHold = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custHold.status).toBe('CREDIT_HOLD');

    const p0 = await createPayment(workspaceId, customerId, { amount_cents: 1_000 }, 'SellerAR');
    const p0Id = getPaymentId(p0);
    await markPaymentCleared(workspaceId, p0Id, 'SellerAR');
    await reversePayment(workspaceId, p0Id, 'SellerAdmin').then(expectSuccess);
    const frozen = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(frozen.status).toBe('FROZEN');
    expect(frozen.unapplied_cash_cents).toBe(0);

    await advancePeriod(workspaceId, 'System');
    const stillFrozen = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(stillFrozen.status).toBe('FROZEN');

    await advancePeriod(workspaceId, 'System');
    const ws4 = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(ws4.period_index).toBe(4);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('CREDIT_HOLD');
    expect(cust.balance_due_cents).toBe(10_000);
    expect(cust.unapplied_cash_cents).toBe(0);
    expect(cust.available_credit_cents).toBe(0);

    const dAfter = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(dAfter.status).toBe('ESCALATED');

    const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter.status).toBe('ACCEPTED');
    expect(invAfter.due_period_index).toBe(10);
    expect(invAfter.collections_stage).toBe('CURRENT');

    const pay = await getPayment(workspaceId, p0Id, 'SellerAdmin');
    expect(pay.status).toBe('REVERSED');

    const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
    const sumDue = all
      .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
      .reduce((acc: number, i: any) => acc + (i.amount_due_cents as number), 0);
    expect(sumDue).toBe(10_000);
    expect(sumDue).toBe(cust.balance_due_cents);
  });
});
