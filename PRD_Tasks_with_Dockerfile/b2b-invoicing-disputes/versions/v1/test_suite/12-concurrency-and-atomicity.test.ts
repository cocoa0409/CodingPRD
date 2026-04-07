import { postAs } from '../../../test-helpers/api-client';
import { expectErrorCode, expectSuccess } from '../../../test-helpers/assertions';
import { repeatConcurrencyTest } from '../../../test-helpers/concurrency';
import { setupWorkspaceCustomerContract } from '../../../test-helpers/fixtures';
import {
  addInvoiceLine,
  advancePeriod,
  createCreditMemo,
  createCustomer,
  createInvoice,
  createPayment,
  createPurchaseOrder,
  createWorkspace,
  getCreditMemo,
  getCreditMemoId,
  getCustomer,
  getCustomerId,
  getDispute,
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
  issueCreditMemo
} from '../../../test-helpers/resources';

function isSuccessStatus(status: number): boolean {
  return status >= 200 && status < 300;
}

describe('Concurrency and Atomicity Tests', () => {
  test('CONCUR_001: concurrent finalize enforces per-period billing cap (exactly one succeeds)', async () => {
    await repeatConcurrencyTest(async () => {
      const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ billing_cap_cents_per_period: 10_000_000 });

      const inv1 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `CAP-${workspaceId}-1` }, 'SellerAR');
      const inv2 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `CAP-${workspaceId}-2` }, 'SellerAR');
      const inv1Id = getInvoiceId(inv1);
      const inv2Id = getInvoiceId(inv2);

      await addInvoiceLine(workspaceId, inv1Id, { description: 'I1', quantity_units: 600, unit_price_cents: 10_000 }, 'SellerAR');
      await addInvoiceLine(workspaceId, inv2Id, { description: 'I2', quantity_units: 500, unit_price_cents: 10_000 }, 'SellerAR');

      const [r1, r2] = await Promise.all([
        postAs(`/workspaces/${workspaceId}/invoices/${inv1Id}/finalize`, { override_hold: false, override_billing_cap: false, final_invoice: false }, 'SellerAR'),
        postAs(`/workspaces/${workspaceId}/invoices/${inv2Id}/finalize`, { override_hold: false, override_billing_cap: false, final_invoice: false }, 'SellerAR')
      ]);

      const successes = [r1, r2].filter((r) => isSuccessStatus(r.status));
      const failures = [r1, r2].filter((r) => !isSuccessStatus(r.status));
      expect(successes).toHaveLength(1);
      expect(failures).toHaveLength(1);
      await expectErrorCode(failures[0], 'ERR_BILLING_CAP_EXCEEDED');

      const i1 = await getInvoice(workspaceId, inv1Id, 'SellerAdmin');
      const i2 = await getInvoice(workspaceId, inv2Id, 'SellerAdmin');
      const finalized = [i1, i2].filter((i) => i.status === 'FINALIZED');
      const drafts = [i1, i2].filter((i) => i.status === 'DRAFT');

      expect(finalized).toHaveLength(1);
      expect(drafts).toHaveLength(1);
      expect(finalized[0].issued_period_index).toBe(0);
      expect(drafts[0].invoice_total_cents).toBe(0);

      const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
      expect(cust.balance_due_cents).toBe(finalized[0].invoice_total_cents);
      expect(cust.balance_due_cents).toBeLessThanOrEqual(10_000_000);
    }, 3);
  });

  test('CONCUR_002: concurrent payment create cannot reserve same balance twice', async () => {
    await repeatConcurrencyTest(async () => {
      const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });

      const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `INV-${workspaceId}` }, 'SellerAR');
      const invoiceId = getInvoiceId(inv);
      await addInvoiceLine(workspaceId, invoiceId, { description: 'Line', quantity_units: 5, unit_price_cents: 10_000 }, 'SellerAR');
      await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/finalize`, { override_hold: false, override_billing_cap: false, final_invoice: false }, 'SellerAR').then(expectSuccess);
      await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
      await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/accept`, {}, 'BuyerAP').then(expectSuccess);

      const [p1, p2] = await Promise.all([
        postAs(`/workspaces/${workspaceId}/customers/${customerId}/payments`, { amount_cents: 50_000, allocations: [{ invoice_id: invoiceId, amount_cents: 50_000 }] }, 'BuyerAP'),
        postAs(`/workspaces/${workspaceId}/customers/${customerId}/payments`, { amount_cents: 50_000, allocations: [{ invoice_id: invoiceId, amount_cents: 50_000 }] }, 'BuyerAP')
      ]);

      const successes = [p1, p2].filter((r) => isSuccessStatus(r.status));
      const failures = [p1, p2].filter((r) => !isSuccessStatus(r.status));
      expect(successes).toHaveLength(1);
      expect(failures).toHaveLength(1);
      await expectErrorCode(failures[0], 'ERR_PAYMENT_EXCEEDS_ALLOWED');

      const created = successes[0].body?.data ?? successes[0].body;
      const paymentId = getPaymentId(created);
      const pay = await getPayment(workspaceId, paymentId, 'SellerAdmin');
      expect(pay.status).toBe('INITIATED');

      const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
      expect(invAfter.amount_due_cents).toBe(50_000);

      const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
      expect(cust.balance_due_cents).toBe(50_000);
    }, 5);
  });

  test('CONCUR_003: concurrent dispute creation allows exactly one active dispute', async () => {
    await repeatConcurrencyTest(async () => {
      const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });

      const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `INV-${workspaceId}` }, 'SellerAR');
      const invoiceId = getInvoiceId(inv);
      await addInvoiceLine(workspaceId, invoiceId, { description: 'Line', quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
      await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/finalize`, { override_hold: false, override_billing_cap: false, final_invoice: false }, 'SellerAR').then(expectSuccess);
      await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
      await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/accept`, {}, 'BuyerAP').then(expectSuccess);

      const invFull = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
      const lineId = getFirstInvoiceLineId(invFull);

      const [d1, d2] = await Promise.all([
        postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/disputes`, { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: 5_000 }] }, 'BuyerAP'),
        postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/disputes`, { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: 5_000 }] }, 'BuyerAP')
      ]);

      const successes = [d1, d2].filter((r) => isSuccessStatus(r.status));
      const failures = [d1, d2].filter((r) => !isSuccessStatus(r.status));
      expect(successes).toHaveLength(1);
      expect(failures).toHaveLength(1);
      await expectErrorCode(failures[0], 'ERR_DISPUTE_ALREADY_ACTIVE');

      const after = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
      expect(after.amount_disputed_cents).toBe(5_000);
      expect(after.amount_disputed_cents).toBeGreaterThanOrEqual(0);
      expect(after.amount_disputed_cents).toBeLessThanOrEqual(after.amount_due_cents);
    }, 5);
  });

  test('CONCUR_004: concurrent receipts cannot exceed 1% tolerance', async () => {
    await repeatConcurrencyTest(async () => {
      const ws = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
      const workspaceId = ws.workspace_id;
      const customer = await createCustomer(workspaceId, {}, 'SellerAdmin');
      const customerId = getCustomerId(customer);

      const po = await createPurchaseOrder(
        workspaceId,
        customerId,
        { po_number: `PO-${workspaceId}`, lines: [{ ordered_units: 100, unit_price_cents: 10_000, is_service: false }] },
        'BuyerAP'
      );
      const poId = getPurchaseOrderId(po);
      const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
      const poLineId = getFirstPurchaseOrderLineId(poFull);

      const [r1, r2] = await Promise.all([
        postAs(`/workspaces/${workspaceId}/purchase_orders/${poId}/record_receipt`, { items: [{ purchase_order_line_id: poLineId, received_units: 60 }] }, 'BuyerAP'),
        postAs(`/workspaces/${workspaceId}/purchase_orders/${poId}/record_receipt`, { items: [{ purchase_order_line_id: poLineId, received_units: 50 }] }, 'BuyerAP')
      ]);

      const successes = [r1, r2].filter((r) => isSuccessStatus(r.status));
      const failures = [r1, r2].filter((r) => !isSuccessStatus(r.status));
      expect(successes).toHaveLength(1);
      expect(failures).toHaveLength(1);
      await expectErrorCode(failures[0], 'ERR_RECEIPT_EXCEEDS_TOLERANCE');

      const got = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
      const received = got.lines[0].received_units;
      expect([50, 60]).toContain(received);
      expect(received).toBeLessThanOrEqual(Math.floor(100 * 1.01));
    }, 5);
  });

  test('CONCUR_005: concurrent finalize enforces external_invoice_ref uniqueness', async () => {
    await repeatConcurrencyTest(async () => {
      const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });
      const externalRef = `ERP-REF-77-${workspaceId}`;

      const i1 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: externalRef }, 'SellerAR');
      const i2 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: externalRef }, 'SellerAR');
      const i1Id = getInvoiceId(i1);
      const i2Id = getInvoiceId(i2);

      await addInvoiceLine(workspaceId, i1Id, { description: 'L1', quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
      await addInvoiceLine(workspaceId, i2Id, { description: 'L2', quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');

      const [r1, r2] = await Promise.all([
        postAs(`/workspaces/${workspaceId}/invoices/${i1Id}/finalize`, { override_hold: false, override_billing_cap: false, final_invoice: false }, 'SellerAR'),
        postAs(`/workspaces/${workspaceId}/invoices/${i2Id}/finalize`, { override_hold: false, override_billing_cap: false, final_invoice: false }, 'SellerAR')
      ]);

      const successes = [r1, r2].filter((r) => isSuccessStatus(r.status));
      const failures = [r1, r2].filter((r) => !isSuccessStatus(r.status));
      expect(successes).toHaveLength(1);
      expect(failures).toHaveLength(1);
      await expectErrorCode(failures[0], 'ERR_DUPLICATE_EXTERNAL_REF');

      const inv1 = await getInvoice(workspaceId, i1Id, 'SellerAdmin');
      const inv2 = await getInvoice(workspaceId, i2Id, 'SellerAdmin');
      const finalized = [inv1, inv2].filter((i) => i.status === 'FINALIZED');
      expect(finalized).toHaveLength(1);
    }, 3);
  });

  test('CONCUR_006: concurrent close_books is non-idempotent (exactly one succeeds)', async () => {
    await repeatConcurrencyTest(async () => {
      const ws = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
      const workspaceId = ws.workspace_id;

      await advancePeriod(workspaceId, 'System');

      const [r1, r2] = await Promise.all([
        postAs(`/workspaces/${workspaceId}/close_books`, {}, 'Auditor'),
        postAs(`/workspaces/${workspaceId}/close_books`, {}, 'Auditor')
      ]);

      const successes = [r1, r2].filter((r) => isSuccessStatus(r.status));
      const failures = [r1, r2].filter((r) => !isSuccessStatus(r.status));
      expect(successes).toHaveLength(1);
      expect(failures).toHaveLength(1);
      await expectErrorCode(failures[0], 'ERR_INVALID_STATE_TRANSITION');

      const got = await getWorkspace(workspaceId, 'SellerAdmin');
      expect(got.books_closed_through_period_index).toBe(0);
    }, 5);
  });

  test('CONCUR_007: concurrent purchase order create enforces po_number uniqueness per customer', async () => {
    await repeatConcurrencyTest(async () => {
      const ws = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
      const workspaceId = ws.workspace_id;
      const customer = await createCustomer(workspaceId, {}, 'SellerAdmin');
      const customerId = getCustomerId(customer);

      const payload = {
        po_number: 'PO-777',
        lines: [{ description: 'Widgets', ordered_units: 10, unit_price_cents: 10_000, is_service: false }]
      };

      const [r1, r2] = await Promise.all([
        postAs(`/workspaces/${workspaceId}/customers/${customerId}/purchase_orders`, payload, 'BuyerAP'),
        postAs(`/workspaces/${workspaceId}/customers/${customerId}/purchase_orders`, payload, 'BuyerAP')
      ]);

      const successes = [r1, r2].filter((r) => isSuccessStatus(r.status));
      const failures = [r1, r2].filter((r) => !isSuccessStatus(r.status));
      expect(successes).toHaveLength(1);
      expect(failures).toHaveLength(1);
      await expectErrorCode(failures[0], 'ERR_DUPLICATE_PO_NUMBER');

      const okBody = successes[0].body?.data ?? successes[0].body;
      const poId = getPurchaseOrderId(okBody);

      const got = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
      expect(got.status).toBe('OPEN');
      expect(got.po_number).toBe('PO-777');
      expect(got.lines[0].received_units).toBe(0);
      expect(got.lines[0].net_billed_units).toBe(0);

      const retry = await postAs(`/workspaces/${workspaceId}/customers/${customerId}/purchase_orders`, payload, 'BuyerAP');
      await expectErrorCode(retry, 'ERR_DUPLICATE_PO_NUMBER');
    }, 5);
  });

  test('CONCUR_008: concurrent invoice finalize vs PO cancel is atomic (not both succeed)', async () => {
    await repeatConcurrencyTest(async () => {
      const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: true });

      const po = await createPurchaseOrder(
        workspaceId,
        customerId,
        { po_number: `PO-${workspaceId}`, lines: [{ description: 'Goods', ordered_units: 10, unit_price_cents: 10_000, is_service: false }] },
        'BuyerAP'
      );
      const poId = getPurchaseOrderId(po);
      const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
      const poLineId = getFirstPurchaseOrderLineId(poFull);

      const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId, external_invoice_ref: `CONCUR-008-${workspaceId}` }, 'SellerAR');
      const invoiceId = getInvoiceId(invoice);
      await addInvoiceLine(workspaceId, invoiceId, { description: 'Line', quantity_units: 10, unit_price_cents: 10_000, purchase_order_line_id: poLineId }, 'SellerAR');

      const [finalizeRes, cancelRes] = await Promise.all([
        postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/finalize`, { override_hold: false, override_billing_cap: false, final_invoice: false }, 'SellerAR'),
        postAs(`/workspaces/${workspaceId}/purchase_orders/${poId}/cancel`, {}, 'BuyerAP')
      ]);

      const finalizeOk = isSuccessStatus(finalizeRes.status);
      const cancelOk = isSuccessStatus(cancelRes.status);
      expect(finalizeOk || cancelOk).toBe(true);
      expect(!(finalizeOk && cancelOk)).toBe(true);

      if (finalizeOk) {
        await expectErrorCode(cancelRes, 'ERR_PO_HAS_INVOICES');
        const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
        expect(inv.status).toBe('FINALIZED');
        expect(inv.invoice_total_cents).toBe(100_000);
        const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
        expect(cust.balance_due_cents).toBe(100_000);
        const poAfter = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
        expect(poAfter.status).toBe('OPEN');
        expect(poAfter.lines[0].net_billed_units).toBe(10);
      } else {
        await expectErrorCode(finalizeRes, 'ERR_PO_NOT_OPEN');
        const poAfter = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
        expect(poAfter.status).toBe('CANCELLED');
        expect(poAfter.lines[0].net_billed_units).toBe(0);
        const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
        expect(inv.status).toBe('DRAFT');
        expect(inv.invoice_total_cents).toBe(0);
        const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
        expect(cust.balance_due_cents).toBe(0);
      }
    }, 5);
  });

  test('CONCUR_009: concurrent goodwill credit memo issue enforces per-customer-per-period cap', async () => {
    await repeatConcurrencyTest(async () => {
      const ws = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
      const workspaceId = ws.workspace_id;
      const customer = await createCustomer(workspaceId, {}, 'SellerAdmin');
      const customerId = getCustomerId(customer);

      const gwA = await createCreditMemo(workspaceId, customerId, { reason: 'GOODWILL', items: [{ quantity_units: 10, unit_price_cents: 10_000 }] }, 'SellerAR');
      const gwB = await createCreditMemo(workspaceId, customerId, { reason: 'GOODWILL', items: [{ quantity_units: 5, unit_price_cents: 10_000 }] }, 'SellerAR');
      await issueCreditMemo(workspaceId, getCreditMemoId(gwA), 'SellerAR');
      await issueCreditMemo(workspaceId, getCreditMemoId(gwB), 'SellerAR');
      const c0 = await getCustomer(workspaceId, customerId, 'SellerAdmin');
      expect(c0.available_credit_cents).toBe(150_000);

      const gw1 = await createCreditMemo(workspaceId, customerId, { reason: 'GOODWILL', items: [{ quantity_units: 10, unit_price_cents: 10_000 }] }, 'SellerAR');
      const gw2 = await createCreditMemo(workspaceId, customerId, { reason: 'GOODWILL', items: [{ quantity_units: 10, unit_price_cents: 10_000 }] }, 'SellerAR');
      const gw1Id = getCreditMemoId(gw1);
      const gw2Id = getCreditMemoId(gw2);

      const [r1, r2] = await Promise.all([
        postAs(`/workspaces/${workspaceId}/credit_memos/${gw1Id}/issue`, {}, 'SellerAR'),
        postAs(`/workspaces/${workspaceId}/credit_memos/${gw2Id}/issue`, {}, 'SellerAR')
      ]);

      const successes = [r1, r2].filter((r) => isSuccessStatus(r.status));
      const failures = [r1, r2].filter((r) => !isSuccessStatus(r.status));
      expect(successes).toHaveLength(1);
      expect(failures).toHaveLength(1);
      await expectErrorCode(failures[0], 'ERR_CREDIT_EXCEEDS_AUTHORITY');

      const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
      expect(cust.available_credit_cents).toBe(250_000);
      expect(cust.balance_due_cents).toBe(0);
      expect(cust.unapplied_cash_cents).toBe(0);

      const cm1 = await getCreditMemo(workspaceId, gw1Id, 'SellerAdmin');
      const cm2 = await getCreditMemo(workspaceId, gw2Id, 'SellerAdmin');
      const issued = [cm1, cm2].filter((cm) => cm.status === 'ISSUED');
      const drafts = [cm1, cm2].filter((cm) => cm.status === 'DRAFT');
      expect(issued).toHaveLength(1);
      expect(drafts).toHaveLength(1);
    }, 5);
  });

  test('CONCUR_010: concurrent apply of same customer-level credit memo to two invoices preserves conservation', async () => {
    await repeatConcurrencyTest(async () => {
      const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();

      const i1 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `CONCUR-010-1-${workspaceId}` }, 'SellerAR');
      const i1Id = getInvoiceId(i1);
      await addInvoiceLine(workspaceId, i1Id, { description: 'I1', quantity_units: 3, unit_price_cents: 10_000 }, 'SellerAR');
      await postAs(`/workspaces/${workspaceId}/invoices/${i1Id}/finalize`, { override_hold: false, override_billing_cap: false, final_invoice: false }, 'SellerAR').then(expectSuccess);
      await postAs(`/workspaces/${workspaceId}/invoices/${i1Id}/send`, {}, 'SellerAR').then(expectSuccess);
      await postAs(`/workspaces/${workspaceId}/invoices/${i1Id}/accept`, {}, 'BuyerAP').then(expectSuccess);

      const i2 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `CONCUR-010-2-${workspaceId}` }, 'SellerAR');
      const i2Id = getInvoiceId(i2);
      await addInvoiceLine(workspaceId, i2Id, { description: 'I2', quantity_units: 2, unit_price_cents: 10_000 }, 'SellerAR');
      await postAs(`/workspaces/${workspaceId}/invoices/${i2Id}/finalize`, { override_hold: false, override_billing_cap: false, final_invoice: false }, 'SellerAR').then(expectSuccess);
      await postAs(`/workspaces/${workspaceId}/invoices/${i2Id}/send`, {}, 'SellerAR').then(expectSuccess);
      await postAs(`/workspaces/${workspaceId}/invoices/${i2Id}/accept`, {}, 'BuyerAP').then(expectSuccess);

      const cust0 = await getCustomer(workspaceId, customerId, 'SellerAdmin');
      expect(cust0.balance_due_cents).toBe(50_000);

      const cm = await createCreditMemo(workspaceId, customerId, { reason: 'GOODWILL', items: [{ quantity_units: 4, unit_price_cents: 10_000 }] }, 'SellerAR');
      const cmId = getCreditMemoId(cm);
      await issueCreditMemo(workspaceId, cmId, 'SellerAR');
      const cust1 = await getCustomer(workspaceId, customerId, 'SellerAdmin');
      expect(cust1.available_credit_cents).toBe(40_000);

      const [a1, a2] = await Promise.all([
        postAs(`/workspaces/${workspaceId}/credit_memos/${cmId}/apply`, { invoice_id: i1Id }, 'SellerAR'),
        postAs(`/workspaces/${workspaceId}/credit_memos/${cmId}/apply`, { invoice_id: i2Id }, 'SellerAR')
      ]);
      expectSuccess(a1);
      expectSuccess(a2);

      const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
      expect(cust.available_credit_cents).toBe(0);
      expect(cust.balance_due_cents).toBe(10_000);

      const inv1 = await getInvoice(workspaceId, i1Id, 'SellerAdmin');
      const inv2 = await getInvoice(workspaceId, i2Id, 'SellerAdmin');
      const dueSet = [inv1.amount_due_cents, inv2.amount_due_cents].sort((x: number, y: number) => x - y);
      expect(dueSet).toEqual([0, 10_000]);
      const closed = [inv1, inv2].find((i) => i.amount_due_cents === 0);
      const open = [inv1, inv2].find((i) => i.amount_due_cents === 10_000);
      expect(closed?.status).toBe('CLOSED');
      expect(open?.status).toBe('ACCEPTED');

      const cmAfter = await getCreditMemo(workspaceId, cmId, 'SellerAdmin');
      expect(cmAfter.status).toBe('ISSUED');

      expect((inv1.amount_due_cents as number) + (inv2.amount_due_cents as number)).toBe(10_000);
    }, 5);
  });

  test('CONCUR_011: concurrent payment create with no allocations reserves balance once (both succeed)', async () => {
    await repeatConcurrencyTest(async () => {
      const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1 });

      const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `CONCUR-011-${workspaceId}` }, 'SellerAR');
      const invoiceId = getInvoiceId(inv);
      await addInvoiceLine(workspaceId, invoiceId, { description: 'Line', quantity_units: 5, unit_price_cents: 10_000 }, 'SellerAR');
      await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/finalize`, { override_hold: false, override_billing_cap: false, final_invoice: false }, 'SellerAR').then(expectSuccess);
      await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
      await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/accept`, {}, 'BuyerAP').then(expectSuccess);

      await advancePeriod(workspaceId, 'System');
      await advancePeriod(workspaceId, 'System');

      const cust0 = await getCustomer(workspaceId, customerId, 'SellerAdmin');
      expect(cust0.balance_due_cents).toBe(50_000);

      const [p1, p2] = await Promise.all([
        postAs(`/workspaces/${workspaceId}/customers/${customerId}/payments`, { amount_cents: 50_000 }, 'BuyerAP'),
        postAs(`/workspaces/${workspaceId}/customers/${customerId}/payments`, { amount_cents: 50_000 }, 'BuyerAP')
      ]);

      expect(isSuccessStatus(p1.status)).toBe(true);
      expect(isSuccessStatus(p2.status)).toBe(true);

      const created1 = p1.body?.data ?? p1.body;
      const created2 = p2.body?.data ?? p2.body;

      const reserved1 = (created1.allocations ?? created1.reserved_allocations ?? created1.reserved ?? []) as any[];
      const reserved2 = (created2.allocations ?? created2.reserved_allocations ?? created2.reserved ?? []) as any[];

      const reservers = [reserved1, reserved2].filter((r) => Array.isArray(r) && r.length > 0);
      expect(reservers).toHaveLength(1);
      expect(reservers[0][0].invoice_id).toBe(invoiceId);
      expect(reservers[0][0].amount_cents).toBe(50_000);

      const pay1 = await getPayment(workspaceId, getPaymentId(created1), 'SellerAdmin');
      const pay2 = await getPayment(workspaceId, getPaymentId(created2), 'SellerAdmin');
      expect(pay1.status).toBe('INITIATED');
      expect(pay2.status).toBe('INITIATED');

      const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
      expect(invAfter.amount_due_cents).toBe(50_000);
      const custAfter = await getCustomer(workspaceId, customerId, 'SellerAdmin');
      expect(custAfter.balance_due_cents).toBe(50_000);
    }, 5);
  });

  test('CONCUR_012: concurrent mark_cleared and dispute creation enforces payable-at-clearing rule', async () => {
    await repeatConcurrencyTest(async () => {
      const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1 });

      const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `CONCUR-012-${workspaceId}` }, 'SellerAR');
      const invoiceId = getInvoiceId(inv);
      await addInvoiceLine(workspaceId, invoiceId, { description: 'Line', quantity_units: 5, unit_price_cents: 10_000 }, 'SellerAR');
      await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/finalize`, { override_hold: false, override_billing_cap: false, final_invoice: false }, 'SellerAR').then(
        expectSuccess
      );
      await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
      await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/accept`, {}, 'BuyerAP').then(expectSuccess);

      const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
      const invoiceLineId = getFirstInvoiceLineId(inv0);

      const payRes = await postAs(
        `/workspaces/${workspaceId}/customers/${customerId}/payments`,
        { amount_cents: 50_000, allocations: [{ invoice_id: invoiceId, amount_cents: 50_000 }] },
        'BuyerAP'
      );
      expectSuccess(payRes);
      const payment = payRes.body?.data ?? payRes.body;
      const paymentId = getPaymentId(payment);
      const custSnap = await getCustomer(workspaceId, customerId, 'SellerAdmin');
      expect(custSnap.balance_due_cents).toBe(50_000);
      expect(custSnap.unapplied_cash_cents).toBe(0);

      const [clearRes, disputeRes] = await Promise.all([
        postAs(`/workspaces/${workspaceId}/payments/${paymentId}/mark_cleared`, {}, 'SellerAR'),
        postAs(
          `/workspaces/${workspaceId}/invoices/${invoiceId}/disputes`,
          { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_amount_cents: 20_000 }] },
          'BuyerAP'
        )
      ]);

      expectSuccess(clearRes);

      const cleared = await getPayment(workspaceId, paymentId, 'SellerAdmin');
      expect(cleared.status).toBe('CLEARED');

      const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
      const custAfter = await getCustomer(workspaceId, customerId, 'SellerAdmin');

      if (isSuccessStatus(disputeRes.status)) {

        const dispute = disputeRes.body?.data ?? disputeRes.body;
        expect(dispute.status).toBe('OPEN');

        expect(invAfter.status).toBe('ACCEPTED');
        expect(invAfter.amount_disputed_cents).toBe(20_000);
        expect(invAfter.amount_due_cents).toBe(20_000);

        expect(custAfter.balance_due_cents).toBe(20_000);
        expect(custAfter.unapplied_cash_cents).toBe(20_000);
      } else {

        await expectErrorCode(disputeRes, 'ERR_INVOICE_NOT_DISPUTABLE');

        expect(invAfter.status).toBe('CLOSED');
        expect(invAfter.amount_due_cents).toBe(0);
        expect(invAfter.amount_disputed_cents).toBe(0);

        expect(custAfter.balance_due_cents).toBe(0);
        expect(custAfter.unapplied_cash_cents).toBe(0);
      }
    }, 5);
  });

  test('CONCUR_013: concurrent mark_cleared on two initiated payments applies at most undisputed payable; remainder becomes unapplied cash', async () => {
    await repeatConcurrencyTest(async () => {
      const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 2 });

      const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `CONCUR-013-${workspaceId}` }, 'SellerAR');
      const invoiceId = getInvoiceId(inv);
      await addInvoiceLine(workspaceId, invoiceId, { description: 'Line', quantity_units: 10, unit_price_cents: 10_000 }, 'SellerAR');
      await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/finalize`, { override_hold: false, override_billing_cap: false, final_invoice: false }, 'SellerAR').then(
        expectSuccess
      );
      await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
      await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/accept`, {}, 'BuyerAP').then(expectSuccess);

      const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
      const invoiceLineId = getFirstInvoiceLineId(inv0);

      const p1Res = await postAs(
        `/workspaces/${workspaceId}/customers/${customerId}/payments`,
        { amount_cents: 50_000, allocations: [{ invoice_id: invoiceId, amount_cents: 50_000 }] },
        'BuyerAP'
      );
      expectSuccess(p1Res);
      const p1Body = p1Res.body?.data ?? p1Res.body;
      const p1Id = getPaymentId(p1Body);

      const p2Res = await postAs(
        `/workspaces/${workspaceId}/customers/${customerId}/payments`,
        { amount_cents: 50_000, allocations: [{ invoice_id: invoiceId, amount_cents: 50_000 }] },
        'BuyerAP'
      );
      expectSuccess(p2Res);
      const p2Body = p2Res.body?.data ?? p2Res.body;
      const p2Id = getPaymentId(p2Body);

      const disputeRes = await postAs(
        `/workspaces/${workspaceId}/invoices/${invoiceId}/disputes`,
        { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_amount_cents: 60_000 }] },
        'BuyerAP'
      );
      expectSuccess(disputeRes);

      const custSnap = await getCustomer(workspaceId, customerId, 'SellerAdmin');
      expect(custSnap.balance_due_cents).toBe(100_000);
      expect(custSnap.unapplied_cash_cents).toBe(0);

      const [c1, c2] = await Promise.all([
        postAs(`/workspaces/${workspaceId}/payments/${p1Id}/mark_cleared`, {}, 'SellerAR'),
        postAs(`/workspaces/${workspaceId}/payments/${p2Id}/mark_cleared`, {}, 'SellerAR')
      ]);
      expectSuccess(c1);
      expectSuccess(c2);

      const p1 = await getPayment(workspaceId, p1Id, 'SellerAdmin');
      const p2 = await getPayment(workspaceId, p2Id, 'SellerAdmin');
      expect(p1.status).toBe('CLEARED');
      expect(p2.status).toBe('CLEARED');

      const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
      expect(invAfter.status).toBe('ACCEPTED');
      expect(invAfter.amount_due_cents).toBe(60_000);
      expect(invAfter.amount_disputed_cents).toBe(60_000);
      expect(invAfter.amount_disputed_cents).toBeGreaterThanOrEqual(0);
      expect(invAfter.amount_disputed_cents).toBeLessThanOrEqual(invAfter.amount_due_cents);

      const custAfter = await getCustomer(workspaceId, customerId, 'SellerAdmin');
      expect(custAfter.balance_due_cents).toBe(60_000);
      expect(custAfter.unapplied_cash_cents).toBe(60_000);
      expect(custAfter.available_credit_cents).toBe(0);
    }, 5);
  });

  test('CONCUR_014: concurrent payment clear and credit apply is atomic (no double settlement)', async () => {
    await repeatConcurrencyTest(async () => {
      const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1 });

      const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `CONCUR-014-${workspaceId}` }, 'SellerAR');
      const invoiceId = getInvoiceId(inv);
      await addInvoiceLine(workspaceId, invoiceId, { description: 'Line', quantity_units: 5, unit_price_cents: 10_000 }, 'SellerAR');
      await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/finalize`, { override_hold: false, override_billing_cap: false, final_invoice: false }, 'SellerAR').then(
        expectSuccess
      );
      await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
      await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/accept`, {}, 'BuyerAP').then(expectSuccess);

      const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
      const lineId = getFirstInvoiceLineId(inv0);

      const payRes = await postAs(
        `/workspaces/${workspaceId}/customers/${customerId}/payments`,
        { amount_cents: 50_000, allocations: [{ invoice_id: invoiceId, amount_cents: 50_000 }] },
        'BuyerAP'
      );
      expectSuccess(payRes);
      const payBody = payRes.body?.data ?? payRes.body;
      const paymentId = getPaymentId(payBody);

      const cm = await createCreditMemo(
        workspaceId,
        customerId,
        { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: lineId, quantity_units: 1, unit_price_cents: 10_000 }] },
        'SellerAR'
      );
      const cmId = getCreditMemoId(cm);
      await issueCreditMemo(workspaceId, cmId, 'SellerAR');

      const snapCust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
      expect(snapCust.available_credit_cents).toBe(10_000);
      const snapInv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
      expect(snapInv.amount_due_cents).toBe(50_000);

      const [clearRes, applyRes] = await Promise.all([
        postAs(`/workspaces/${workspaceId}/payments/${paymentId}/mark_cleared`, {}, 'SellerAR'),
        postAs(`/workspaces/${workspaceId}/credit_memos/${cmId}/apply`, { invoice_id: invoiceId }, 'SellerAR')
      ]);

      expectSuccess(clearRes);
      const payment = await getPayment(workspaceId, paymentId, 'SellerAdmin');
      expect(payment.status).toBe('CLEARED');

      const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
      const custAfter = await getCustomer(workspaceId, customerId, 'SellerAdmin');

      if (isSuccessStatus(applyRes.status)) {

        expect(invAfter.status).toBe('CLOSED');
        expect(invAfter.amount_due_cents).toBe(0);
        expect(invAfter.amount_disputed_cents).toBe(0);

        expect(custAfter.balance_due_cents).toBe(0);
        expect(custAfter.available_credit_cents).toBe(0);
        expect(custAfter.unapplied_cash_cents).toBe(10_000);
      } else {

        await expectErrorCode(applyRes, 'ERR_INVOICE_NOT_CREDITABLE');

        expect(invAfter.status).toBe('CLOSED');
        expect(invAfter.amount_due_cents).toBe(0);
        expect(invAfter.amount_disputed_cents).toBe(0);

        expect(custAfter.balance_due_cents).toBe(0);
        expect(custAfter.available_credit_cents).toBe(10_000);
        expect(custAfter.unapplied_cash_cents).toBe(0);
      }

      expect(custAfter.balance_due_cents).toBe(0);
    }, 5);
  });

  test('CONCUR_015: close_books vs mark_cleared races pending-payments check but cash remains conserved', async () => {
    await repeatConcurrencyTest(async () => {
      const ws = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
      const workspaceId = ws.workspace_id;
      const customer = await createCustomer(workspaceId, {}, 'SellerAdmin');
      const customerId = getCustomerId(customer);

      const payRes = await postAs(`/workspaces/${workspaceId}/customers/${customerId}/payments`, { amount_cents: 1_000 }, 'BuyerAP');
      expectSuccess(payRes);
      const payBody = payRes.body?.data ?? payRes.body;
      const paymentId = getPaymentId(payBody);

      await advancePeriod(workspaceId, 'System');

      const p0 = await getPayment(workspaceId, paymentId, 'SellerAdmin');
      expect(p0.status).toBe('INITIATED');

      const [clearRes, closeRes] = await Promise.all([
        postAs(`/workspaces/${workspaceId}/payments/${paymentId}/mark_cleared`, {}, 'SellerAR'),
        postAs(`/workspaces/${workspaceId}/close_books`, {}, 'Auditor')
      ]);

      expectSuccess(clearRes);
      const cleared = await getPayment(workspaceId, paymentId, 'SellerAdmin');
      expect(cleared.status).toBe('CLEARED');

      const w = await getWorkspace(workspaceId, 'SellerAdmin');
      expect(w.period_index).toBe(1);

      if (isSuccessStatus(closeRes.status)) {
        expectSuccess(closeRes);
        expect(w.books_closed_through_period_index).toBe(0);
      } else {
        await expectErrorCode(closeRes, 'ERR_PERIOD_HAS_PENDING_PAYMENTS');
        expect(w.books_closed_through_period_index == null).toBe(true);
      }

      const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
      expect(cust.balance_due_cents).toBe(0);
      expect(cust.unapplied_cash_cents).toBe(1_000);
      expect(cust.available_credit_cents).toBe(0);
    }, 5);
  });

  test('CONCUR_016: concurrent accept_resolution vs withdraw yields exactly one terminal dispute transition', async () => {
    await repeatConcurrencyTest(async () => {
      const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1 });

      const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `CONCUR-016-${workspaceId}` }, 'SellerAR');
      const invoiceId = getInvoiceId(inv);
      await addInvoiceLine(workspaceId, invoiceId, { description: 'Line', quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
      await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/finalize`, { override_hold: false, override_billing_cap: false, final_invoice: false }, 'SellerAR').then(
        expectSuccess
      );
      await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
      await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/accept`, {}, 'BuyerAP').then(expectSuccess);

      const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
      const lineId = getFirstInvoiceLineId(inv0);

      const disputeRes = await postAs(
        `/workspaces/${workspaceId}/invoices/${invoiceId}/disputes`,
        { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: 10_000 }] },
        'BuyerAP'
      );
      expectSuccess(disputeRes);
      const disputeBody = disputeRes.body?.data ?? disputeRes.body;
      const disputeId = disputeBody.dispute_id ?? disputeBody.id;
      if (!disputeId) throw new Error('Could not resolve dispute_id');

      const prop = await postAs(
        `/workspaces/${workspaceId}/disputes/${disputeId}/propose_resolution`,
        { proposed_credit: { items: [{ invoice_line_id: lineId, quantity_units: 1, unit_price_cents: 10_000 }] } },
        'SellerAR'
      );
      expectSuccess(prop);

      const [acceptRes, withdrawRes] = await Promise.all([
        postAs(`/workspaces/${workspaceId}/disputes/${disputeId}/accept_resolution`, {}, 'BuyerAP'),
        postAs(`/workspaces/${workspaceId}/disputes/${disputeId}/withdraw`, {}, 'BuyerAP')
      ]);

      const successes = [acceptRes, withdrawRes].filter((r) => isSuccessStatus(r.status));
      const failures = [acceptRes, withdrawRes].filter((r) => !isSuccessStatus(r.status));
      expect(successes).toHaveLength(1);
      expect(failures).toHaveLength(1);
      await expectErrorCode(failures[0], 'ERR_INVALID_STATE_TRANSITION');

      const d = await getDispute(workspaceId, disputeId, 'SellerAdmin');
      const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
      const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');

      if (isSuccessStatus(acceptRes.status)) {
        expect(d.status).toBe('CLOSED');
        expect(invAfter.status).toBe('CLOSED');
        expect(invAfter.amount_due_cents).toBe(0);
        expect(invAfter.amount_disputed_cents).toBe(0);
        expect(cust.balance_due_cents).toBe(0);
      } else {
        expect(d.status).toBe('WITHDRAWN');
        expect(invAfter.status).toBe('ACCEPTED');
        expect(invAfter.amount_due_cents).toBe(10_000);
        expect(invAfter.amount_disputed_cents).toBe(0);
        expect(cust.balance_due_cents).toBe(10_000);
      }

      expect(invAfter.amount_due_cents).toBe(cust.balance_due_cents);
      expect(cust.unapplied_cash_cents).toBe(0);
      expect(cust.available_credit_cents).toBe(0);
    }, 5);
  });

  test('CONCUR_017: concurrent advance_period twice results in two period increments and two finance charges in successive periods', async () => {
    await repeatConcurrencyTest(async () => {
      const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1 });

      const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `CONCUR-017-${workspaceId}` }, 'SellerAR');
      const invoiceId = getInvoiceId(inv);
      await addInvoiceLine(workspaceId, invoiceId, { description: 'Line', quantity_units: 10, unit_price_cents: 10_000 }, 'SellerAR');
      await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/finalize`, { override_hold: false, override_billing_cap: false, final_invoice: false }, 'SellerAR').then(
        expectSuccess
      );
      await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
      await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/accept`, {}, 'BuyerAP').then(expectSuccess);

      await advancePeriod(workspaceId, 'System');
      await advancePeriod(workspaceId, 'System');

      const snap = await getCustomer(workspaceId, customerId, 'SellerAdmin');
      expect(snap.balance_due_cents).toBe(100_000);

      const [a1, a2] = await Promise.all([
        postAs(`/workspaces/${workspaceId}/advance_period`, {}, 'System'),
        postAs(`/workspaces/${workspaceId}/advance_period`, {}, 'System')
      ]);
      expectSuccess(a1);
      expectSuccess(a2);

      const ws = await getWorkspace(workspaceId, 'SellerAdmin');
      expect(ws.period_index).toBe(4);

      const charges = await listInvoices(workspaceId, { customer_id: customerId, type: 'FINANCE_CHARGE' }, 'SellerAdmin');
      expect(charges).toHaveLength(2);

      const ids = charges.map((c: any) => getInvoiceId(c));
      const fA = await getInvoice(workspaceId, ids[0], 'SellerAdmin');
      const fB = await getInvoice(workspaceId, ids[1], 'SellerAdmin');

      const issuedSet = new Set([fA.issued_period_index, fB.issued_period_index]);
      expect(Array.from(issuedSet).sort((x: number, y: number) => x - y)).toEqual([3, 4]);

      for (const f of [fA, fB]) {
        expect(f.type).toBe('FINANCE_CHARGE');
        expect(f.status).toBe('ACCEPTED');
        expect(f.reference_invoice_id).toBe(invoiceId);
        expect(f.invoice_total_cents).toBe(2_500);
        expect(f.amount_due_cents).toBe(2_500);
        expect(f.due_period_index).toBe((f.issued_period_index as number) + 1);
      }

      const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
      expect(invAfter.status).toBe('ACCEPTED');
      expect(invAfter.amount_due_cents).toBe(100_000);

      const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
      expect(cust.balance_due_cents).toBe(105_000);
      expect(cust.balance_due_cents).toBe(100_000 + 2_500 + 2_500);
    }, 3);
  });

  test('CONCUR_018: only one final true-up invoice can be finalized under a SUSPENDED contract (concurrent finalize)', async () => {
    await repeatConcurrencyTest(async () => {
      const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ requires_po: false });

      await postAs(`/workspaces/${workspaceId}/contracts/${contractId}/suspend`, {}, 'SellerAdmin').then(expectSuccess);

      const i1 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `CONCUR-018-1-${workspaceId}` }, 'SellerAR');
      const i2 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `CONCUR-018-2-${workspaceId}` }, 'SellerAR');
      const i1Id = getInvoiceId(i1);
      const i2Id = getInvoiceId(i2);

      await addInvoiceLine(workspaceId, i1Id, { description: 'I1', quantity_units: 15, unit_price_cents: 10_000 }, 'SellerAR');
      await addInvoiceLine(workspaceId, i2Id, { description: 'I2', quantity_units: 15, unit_price_cents: 10_000 }, 'SellerAR');

      const [r1, r2] = await Promise.all([
        postAs(`/workspaces/${workspaceId}/invoices/${i1Id}/finalize`, { override_hold: false, override_billing_cap: false, final_invoice: true }, 'SellerAdmin'),
        postAs(`/workspaces/${workspaceId}/invoices/${i2Id}/finalize`, { override_hold: false, override_billing_cap: false, final_invoice: true }, 'SellerAdmin')
      ]);

      const successes = [r1, r2].filter((r) => isSuccessStatus(r.status));
      const failures = [r1, r2].filter((r) => !isSuccessStatus(r.status));
      expect(successes).toHaveLength(1);
      expect(failures).toHaveLength(1);
      await expectErrorCode(failures[0], 'ERR_CONTRACT_INACTIVE');

      const inv1 = await getInvoice(workspaceId, i1Id, 'SellerAdmin');
      const inv2 = await getInvoice(workspaceId, i2Id, 'SellerAdmin');
      const finalized = [inv1, inv2].filter((i) => i.status === 'FINALIZED');
      const drafts = [inv1, inv2].filter((i) => i.status === 'DRAFT');
      expect(finalized).toHaveLength(1);
      expect(drafts).toHaveLength(1);

      expect(finalized[0].invoice_total_cents).toBe(150_000);
      expect(finalized[0].amount_due_cents).toBe(150_000);
      expect(finalized[0].issued_period_index).toBe(0);
      expect(drafts[0].invoice_total_cents).toBe(0);
      expect(drafts[0].issued_period_index == null).toBe(true);

      const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
      expect(cust.balance_due_cents).toBe(150_000);
      expect(cust.unapplied_cash_cents).toBe(0);
      expect(cust.available_credit_cents).toBe(0);

      const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
      const sumDue = (all as any[])
        .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
        .reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
      expect(sumDue).toBe(150_000);
      expect(sumDue).toBe(cust.balance_due_cents);
    }, 5);
  });

  test('CONCUR_019: mark_cleared vs mark_failed race yields exactly one terminal status and consistent customer cash', async () => {
    await repeatConcurrencyTest(async () => {
      const ws = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
      const workspaceId = ws.workspace_id;
      const customer = await createCustomer(workspaceId, {}, 'SellerAdmin');
      const customerId = getCustomerId(customer);

      const p = await createPayment(workspaceId, customerId, { amount_cents: 10_000 }, 'BuyerAP');
      const paymentId = getPaymentId(p);
      expect(p.status).toBe('INITIATED');

      const snap = await getCustomer(workspaceId, customerId, 'SellerAdmin');
      expect(snap.unapplied_cash_cents).toBe(0);
      expect(snap.balance_due_cents).toBe(0);
      expect(snap.available_credit_cents).toBe(0);

      const [clearRes, failRes] = await Promise.all([
        postAs(`/workspaces/${workspaceId}/payments/${paymentId}/mark_cleared`, {}, 'SellerAR'),
        postAs(`/workspaces/${workspaceId}/payments/${paymentId}/mark_failed`, {}, 'SellerAR')
      ]);

      const successes = [clearRes, failRes].filter((r) => isSuccessStatus(r.status));
      const failures = [clearRes, failRes].filter((r) => !isSuccessStatus(r.status));
      expect(successes).toHaveLength(1);
      expect(failures).toHaveLength(1);
      await expectErrorCode(failures[0], 'ERR_INVALID_STATE_TRANSITION');

      const pay = await getPayment(workspaceId, paymentId, 'SellerAdmin');
      const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');

      if (isSuccessStatus(clearRes.status)) {
        expect(pay.status).toBe('CLEARED');
        expect(cust.unapplied_cash_cents).toBe(10_000);
        expect(cust.balance_due_cents).toBe(0);
      } else {
        expect(pay.status).toBe('FAILED');
        expect(cust.unapplied_cash_cents).toBe(0);
        expect(cust.balance_due_cents).toBe(0);
      }

      const invs = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
      const sumDue = (invs as any[])
        .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
        .reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
      expect(sumDue).toBe(0);
      expect(sumDue).toBe(cust.balance_due_cents);
    }, 5);
  });

  test('CONCUR_020: concurrent void vs finalize with same external_invoice_ref is consistent (no duplicate active refs)', async () => {
    await repeatConcurrencyTest(async () => {
      const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract();

      const ref = 'REF-RACE';

      const i1 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: ref }, 'SellerAR');
      const i1Id = getInvoiceId(i1);
      await addInvoiceLine(workspaceId, i1Id, { description: 'I1', quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
      await postAs(`/workspaces/${workspaceId}/invoices/${i1Id}/finalize`, { override_hold: false, override_billing_cap: false, final_invoice: false }, 'SellerAR').then(
        expectSuccess
      );

      const inv1Finalized = await getInvoice(workspaceId, i1Id, 'SellerAdmin');
      expect(inv1Finalized.status).toBe('FINALIZED');
      expect(inv1Finalized.invoice_total_cents).toBe(10_000);
      expect(inv1Finalized.amount_due_cents).toBe(10_000);
      expect(inv1Finalized.issued_period_index).toBe(0);

      const i2 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: ref }, 'SellerAR');
      const i2Id = getInvoiceId(i2);
      await addInvoiceLine(workspaceId, i2Id, { description: 'I2', quantity_units: 1, unit_price_cents: 12_000 }, 'SellerAR');

      const [voidRes, finRes] = await Promise.all([
        postAs(`/workspaces/${workspaceId}/invoices/${i1Id}/void`, {}, 'SellerAR'),
        postAs(`/workspaces/${workspaceId}/invoices/${i2Id}/finalize`, { override_hold: false, override_billing_cap: false, final_invoice: false }, 'SellerAR')
      ]);

      expectSuccess(voidRes);

      const inv1 = await getInvoice(workspaceId, i1Id, 'SellerAdmin');
      const inv2 = await getInvoice(workspaceId, i2Id, 'SellerAdmin');
      expect(inv1.status).toBe('VOIDED');
      expect(inv1.amount_due_cents).toBe(0);

      const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');

      if (isSuccessStatus(finRes.status)) {
        expectSuccess(finRes);
        expect(inv2.status).toBe('FINALIZED');
        expect(inv2.invoice_total_cents).toBe(12_000);
        expect(inv2.amount_due_cents).toBe(12_000);
        expect(inv2.issued_period_index).toBe(0);
        expect(cust.balance_due_cents).toBe(12_000);
      } else {
        await expectErrorCode(finRes, 'ERR_DUPLICATE_EXTERNAL_REF');
        expect(inv2.status).toBe('DRAFT');
        expect(inv2.invoice_total_cents).toBe(0);
        expect(inv2.issued_period_index == null).toBe(true);
        expect(cust.balance_due_cents).toBe(0);
      }

      const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
      const activeFinalized = (all as any[]).filter(
        (i: any) => i.external_invoice_ref === ref && i.status === 'FINALIZED' && i.status !== 'VOIDED'
      );
      expect(activeFinalized).toHaveLength(isSuccessStatus(finRes.status) ? 1 : 0);

      const sumDue = (all as any[])
        .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
        .reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
      expect(sumDue).toBe(cust.balance_due_cents);
    }, 5);
  });

  test('CONCUR_021: concurrent write_off vs dispute creation yields exactly one consistent terminal path', async () => {
    await repeatConcurrencyTest(async () => {
      const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 1 });

      const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `CONCUR-021-${workspaceId}` }, 'SellerAR');
      const invoiceId = getInvoiceId(inv);
      await addInvoiceLine(workspaceId, invoiceId, { description: 'Line', quantity_units: 15, unit_price_cents: 1_000 }, 'SellerAR');
      await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/finalize`, { override_hold: false, override_billing_cap: false, final_invoice: false }, 'SellerAR').then(
        expectSuccess
      );
      await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
      await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/accept`, {}, 'BuyerAP').then(expectSuccess);

      await advancePeriod(workspaceId, 'System');
      await advancePeriod(workspaceId, 'System');
      await advancePeriod(workspaceId, 'System');
      await advancePeriod(workspaceId, 'System');

      const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
      expect(inv0.collections_stage).toBe('COLLECTIONS');
      expect(inv0.amount_due_cents).toBe(15_000);
      expect(inv0.amount_disputed_cents).toBe(0);
      const lineId = getFirstInvoiceLineId(inv0);

      const [writeOffRes, disputeRes] = await Promise.all([
        postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/write_off`, {}, 'SellerAR'),
        postAs(
          `/workspaces/${workspaceId}/invoices/${invoiceId}/disputes`,
          { reason: 'DUPLICATE_INVOICE', items: [{ invoice_line_id: lineId, disputed_amount_cents: 15_000 }] },
          'BuyerAP'
        )
      ]);

      const successes = [writeOffRes, disputeRes].filter((r) => isSuccessStatus(r.status));
      const failures = [writeOffRes, disputeRes].filter((r) => !isSuccessStatus(r.status));
      expect(successes).toHaveLength(1);
      expect(failures).toHaveLength(1);

      const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
      const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');

      if (isSuccessStatus(writeOffRes.status)) {
        expectSuccess(writeOffRes);
        await expectErrorCode(disputeRes, 'ERR_INVOICE_NOT_DISPUTABLE');
        expect(invAfter.status).toBe('CLOSED');
        expect(invAfter.amount_due_cents).toBe(0);
        expect(invAfter.amount_disputed_cents).toBe(0);
        expect(invAfter.collections_stage).toBe('CURRENT');
        expect(cust.status).toBe('ACTIVE');
        expect(cust.balance_due_cents).toBe(5_000);
      } else {
        expectSuccess(disputeRes, 201);
        await expectErrorCode(writeOffRes, 'ERR_INVOICE_HAS_DISPUTE');
        expect(invAfter.status).toBe('ACCEPTED');
        expect(invAfter.amount_due_cents).toBe(15_000);
        expect(invAfter.amount_disputed_cents).toBe(15_000);
        expect(invAfter.collections_stage).toBe('CURRENT');
        expect(cust.status).toBe('ACTIVE');
        expect(cust.balance_due_cents).toBe(20_000);
      }

      const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
      const sumDue = (all as any[])
        .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
        .reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
      expect(sumDue).toBe(cust.balance_due_cents);
    }, 5);
  });

  test('CONCUR_022: concurrent accept_resolution vs advance_period yields exactly one terminal dispute path and no finance charges', async () => {
    await repeatConcurrencyTest(async () => {
      const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract({ payment_terms_periods: 10 });

      const inv = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `CONCUR-022-${workspaceId}` }, 'SellerAR');
      const invoiceId = getInvoiceId(inv);
      await addInvoiceLine(workspaceId, invoiceId, { description: 'Line', quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');
      await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/finalize`, { override_hold: false, override_billing_cap: false, final_invoice: false }, 'SellerAR').then(
        expectSuccess
      );
      await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
      await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/accept`, {}, 'BuyerAP').then(expectSuccess);

      const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
      const lineId = getFirstInvoiceLineId(inv0);

      const disputeRes = await postAs(
        `/workspaces/${workspaceId}/invoices/${invoiceId}/disputes`,
        { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: 10_000 }] },
        'BuyerAP'
      );
      expectSuccess(disputeRes, 201);
      const disputeBody = disputeRes.body?.data ?? disputeRes.body;
      const disputeId = disputeBody.dispute_id ?? disputeBody.id;
      if (!disputeId) throw new Error('Could not resolve dispute_id');

      const prop = await postAs(
        `/workspaces/${workspaceId}/disputes/${disputeId}/propose_resolution`,
        { proposed_credit: { items: [{ invoice_line_id: lineId, quantity_units: 1, unit_price_cents: 10_000 }] } },
        'SellerAR'
      );
      expectSuccess(prop);

      const list = await listCreditMemos(workspaceId, { customer_id: customerId }, 'SellerAdmin');
      const arr = Array.isArray(list) ? list : (list as any)?.items ?? (list as any)?.data ?? [];
      const draft = (arr as any[]).find((cm: any) => cm.status === 'DRAFT');
      if (!draft) throw new Error('Expected a DRAFT credit memo from propose_resolution');
      const cmId = getCreditMemoId(draft);

      await advancePeriod(workspaceId, 'System');
      await advancePeriod(workspaceId, 'System');

      const d0 = await getDispute(workspaceId, disputeId, 'SellerAdmin');
      expect(d0.status).toBe('PROPOSED');

      const [accRes, advRes] = await Promise.all([
        postAs(`/workspaces/${workspaceId}/disputes/${disputeId}/accept_resolution`, {}, 'BuyerAP'),
        postAs(`/workspaces/${workspaceId}/advance_period`, {}, 'System')
      ]);
      expectSuccess(advRes);

      const ws = await getWorkspace(workspaceId, 'SellerAdmin');
      expect(ws.period_index).toBe(3);
      const ids = (advRes.body?.data ?? advRes.body)?.finance_charge_invoice_ids ?? (advRes as any).finance_charge_invoice_ids ?? [];
      expect(Array.isArray(ids)).toBe(true);
      expect(ids).toHaveLength(0);

      const d = await getDispute(workspaceId, disputeId, 'SellerAdmin');
      const cm = await getCreditMemo(workspaceId, cmId, 'SellerAdmin');
      const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
      const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');

      if (isSuccessStatus(accRes.status)) {
        expectSuccess(accRes);
        expect(d.status).toBe('CLOSED');
        expect(cm.status).toBe('ISSUED');
        expect(invAfter.status).toBe('CLOSED');
        expect(invAfter.amount_due_cents).toBe(0);
        expect(invAfter.amount_disputed_cents).toBe(0);
        expect(cust.status).toBe('ACTIVE');
        expect(cust.balance_due_cents).toBe(0);
      } else {
        await expectErrorCode(accRes, 'ERR_INVALID_STATE_TRANSITION');
        expect(d.status).toBe('WITHDRAWN');
        expect(cm.status).toBe('VOIDED');
        expect(invAfter.status).toBe('ACCEPTED');
        expect(invAfter.amount_due_cents).toBe(10_000);
        expect(invAfter.amount_disputed_cents).toBe(0);
        expect(cust.status).toBe('ACTIVE');
        expect(cust.balance_due_cents).toBe(10_000);
      }

      expect(cust.unapplied_cash_cents).toBe(0);
      expect(cust.available_credit_cents).toBe(0);

      const all = await listInvoices(workspaceId, { customer_id: customerId }, 'SellerAdmin');
      const sumDue = (all as any[])
        .filter((i: any) => i.status !== 'DRAFT' && i.status !== 'VOIDED')
        .reduce((s: number, i: any) => s + Number(i.amount_due_cents ?? 0), 0);
      expect(sumDue).toBe(cust.balance_due_cents);
    }, 5);
  });
});
