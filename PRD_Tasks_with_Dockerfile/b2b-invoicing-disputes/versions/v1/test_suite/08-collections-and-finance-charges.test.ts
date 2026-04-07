import { postAs } from '../../../test-helpers/api-client';
import { expectErrorCode, expectSuccess } from '../../../test-helpers/assertions';
import { computeFinanceChargeCents } from '../../../test-helpers/calculations';
import { advanceToPeriod, setupWorkspaceCustomerContract as setupWorkspaceCustomerContractFixture } from '../../../test-helpers/fixtures';
import {
  acceptInvoice,
  activateContract,
  addInvoiceLine,
  advancePeriod,
  applyCreditMemo,
  createContract,
  createCustomer,
  createCreditMemo,
  createDispute,
  createInvoice,
  createPayment,
  createWorkspace,
  finalizeInvoice,
  getContractId,
  getCustomer,
  getCustomerId,
  getCreditMemoId,
  getFirstInvoiceLineId,
  getInvoice,
  getInvoiceId,
  getPaymentId,
  getWorkspace,
  issueCreditMemo,
  listInvoices,
  markPaymentCleared,
  uniqueId
} from '../../../test-helpers/resources';

describe('Collections and Finance Charge Tests', () => {
  async function setupWorkspaceCustomerContract(terms: number = 1) {
    return setupWorkspaceCustomerContractFixture({ payment_terms_periods: terms, requires_po: false });
  }

  async function createAcceptedInvoice(params: { workspaceId: string; customerId: string; contractId: string; amountCents: number }) {
    const invoice = await createInvoice(params.workspaceId, params.customerId, { contract_id: params.contractId, external_invoice_ref: `INV-${uniqueId('ref')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);

    await addInvoiceLine(params.workspaceId, invoiceId, { description: 'Line', quantity_units: 1, unit_price_cents: params.amountCents }, 'SellerAR');
    await finalizeInvoice(params.workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${params.workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(params.workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);
    return invoiceId;
  }

  async function makeInvoiceOverdueAtPeriod(workspaceId: string, invoiceId: string, targetPeriodIndex: number) {
    await advanceToPeriod(workspaceId, targetPeriodIndex);
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    return inv;
  }

  async function triggerFinanceCharges(workspaceId: string) {
    const out = await advancePeriod(workspaceId, 'System');
    return out;
  }

  test('COL_001: collections_stage is REMINDER at 1 period past due', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract(1);
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountCents: 10_000 });

    await advanceToPeriod(workspaceId, 2);
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.collections_stage).toBe('REMINDER');
  });

  test('COL_002: fully disputed invoice generates no finance charges', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract(1);
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountCents: 100_000 });

    await advanceToPeriod(workspaceId, 2);
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const lineId = getFirstInvoiceLineId(inv);

    await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: 100_000 }] },
      'BuyerAP'
    );

    const out = await triggerFinanceCharges(workspaceId);
    const ids: string[] = out.finance_charge_invoice_ids ?? [];
    expect(out.period_index).toBe(3);
    expect(ids).toHaveLength(0);
  });

  test('COL_003: partially disputed overdue invoice still generates a finance charge invoice', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract(1);
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountCents: 300_000 });

    await advanceToPeriod(workspaceId, 2);
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const lineId = getFirstInvoiceLineId(inv);

    await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: 100_000 }] },
      'BuyerAP'
    );

    const before = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    const out = await triggerFinanceCharges(workspaceId);
    const ids: string[] = out.finance_charge_invoice_ids ?? [];
    expect(out.period_index).toBe(3);
    expect(ids).toHaveLength(1);

    const f = await getInvoice(workspaceId, ids[0], 'SellerAdmin');
    expect(f.type).toBe('FINANCE_CHARGE');
    expect(f.status).toBe('ACCEPTED');
    expect(f.issued_period_index).toBe(3);
    expect(f.accepted_period_index).toBe(3);
    expect(f.due_period_index).toBe(4);
    expect(f.invoice_total_cents).toBe(3_000);
    expect(f.amount_due_cents).toBe(3_000);

    const after = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(after.balance_due_cents).toBe((before.balance_due_cents as number) + 3_000);
  });

  test('COL_004: finance charge amount is 15000 cents for 1,000,000 overdue', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract(1);
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountCents: 1_000_000 });

    await makeInvoiceOverdueAtPeriod(workspaceId, invoiceId, 2);

    const out = await triggerFinanceCharges(workspaceId);
    const ids: string[] = out.finance_charge_invoice_ids ?? [];
    expect(ids.length).toBe(1);

    const f = await getInvoice(workspaceId, ids[0], 'SellerAdmin');
    expect(f.type).toBe('FINANCE_CHARGE');
    expect(f.invoice_total_cents).toBe(15_000);
    expect(f.amount_due_cents).toBe(15_000);
  });

  test('COL_005: finance charge minimum is 2500 cents when overdue is small', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract(1);
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountCents: 10_000 });

    await makeInvoiceOverdueAtPeriod(workspaceId, invoiceId, 2);
    const out = await triggerFinanceCharges(workspaceId);
    const ids: string[] = out.finance_charge_invoice_ids ?? [];
    expect(ids.length).toBe(1);

    const f = await getInvoice(workspaceId, ids[0], 'SellerAdmin');
    expect(f.invoice_total_cents).toBe(2_500);
    expect(f.invoice_total_cents).toBe(computeFinanceChargeCents(10_000));
  });

  test('COL_006: finance charge invoices are accepted automatically and due in one period', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract(1);
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountCents: 100_000 });

    await makeInvoiceOverdueAtPeriod(workspaceId, invoiceId, 2);
    const out = await triggerFinanceCharges(workspaceId);
    const ids: string[] = out.finance_charge_invoice_ids ?? [];
    expect(ids.length).toBe(1);
    const financeId = ids[0];

    const f = await getInvoice(workspaceId, financeId, 'SellerAdmin');
    expect(f.type).toBe('FINANCE_CHARGE');
    expect(f.status).toBe('ACCEPTED');
    expect(f.issued_period_index).toBe(f.accepted_period_index);
    expect(f.delivered_period_index).toBe(f.accepted_period_index);
    expect(f.due_period_index).toBe((f.issued_period_index as number) + 1);
  });

  test('COL_007: finance charge invoices only allow FRAUD/DUPLICATE disputes (ERR_DISPUTE_REASON_NOT_ALLOWED)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract(1);
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountCents: 100_000 });

    await advanceToPeriod(workspaceId, 2);
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const lineId = getFirstInvoiceLineId(inv);
    await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: 30_000 }] },
      'BuyerAP'
    );

    const out = await triggerFinanceCharges(workspaceId);
    const ids: string[] = out.finance_charge_invoice_ids ?? [];
    expect(ids.length).toBe(1);
    const financeId = ids[0];

    const fin = await getInvoice(workspaceId, financeId, 'SellerAdmin');
    const finLineId = getFirstInvoiceLineId(fin);

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${financeId}/disputes`,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: finLineId, disputed_units: 1 }] },
      'BuyerAP'
    );
    await expectErrorCode(res, 'ERR_DISPUTE_REASON_NOT_ALLOWED');
  });

  test('COL_009: TAX_ERROR dispute blocked in COLLECTIONS (ERR_COLLECTIONS_RESTRICTS_DISPUTES)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract(1);
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountCents: 10_000 });

    await advanceToPeriod(workspaceId, 4);
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.collections_stage).toBe('COLLECTIONS');
    const lineId = getFirstInvoiceLineId(inv);

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/disputes`,
      { reason: 'TAX_ERROR', items: [{ invoice_line_id: lineId, disputed_amount_cents: 1000 }] },
      'BuyerAP'
    );
    await expectErrorCode(res, 'ERR_COLLECTIONS_RESTRICTS_DISPUTES');
  });

  test('COL_010: paying undisputed portion clears collections_stage but leaves disputed due', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract(1);
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountCents: 100_000 });

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const lineId = getFirstInvoiceLineId(inv0);
    await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: 30_000 }] },
      'BuyerAP'
    );

    await advanceToPeriod(workspaceId, 4);
    const invCollections = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invCollections.collections_stage).toBe('COLLECTIONS');
    expect(invCollections.amount_disputed_cents).toBe(30_000);

    const payment = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: 70_000, allocations: [{ invoice_id: invoiceId, amount_cents: 70_000 }] },
      'BuyerAP'
    );
    await markPaymentCleared(workspaceId, getPaymentId(payment), 'SellerAR');

    const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter.collections_stage).toBe('CURRENT');
    expect(invAfter.amount_due_cents).toBe(30_000);
    expect(invAfter.amount_disputed_cents).toBe(30_000);
  });

  test('COL_011: fully disputed overdue invoice does not put customer on hold', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract(1);
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountCents: 100_000 });

    await advanceToPeriod(workspaceId, 2);
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const lineId = getFirstInvoiceLineId(inv);
    await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: 100_000 }] },
      'BuyerAP'
    );

    await triggerFinanceCharges(workspaceId);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('ACTIVE');
  });

  test('COL_012: partial disputes do not prevent COLLECTIONS when undisputed overdue remains', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract(1);
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountCents: 100_000 });

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const lineId = getFirstInvoiceLineId(inv0);
    await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: 10_000 }] },
      'BuyerAP'
    );

    await advanceToPeriod(workspaceId, 4);
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.collections_stage).toBe('COLLECTIONS');
  });

  test('COL_013: write_off succeeds for <= $200 remaining due in COLLECTIONS (no dispute)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract(1);
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountCents: 15_000 });

    await advanceToPeriod(workspaceId, 4);
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.collections_stage).toBe('COLLECTIONS');
    expect(inv.amount_due_cents).toBe(15_000);

    const res = await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/write_off`, {}, 'SellerAR');
    expectSuccess(res);

    const after = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(after.status).toBe('CLOSED');
    expect(after.amount_due_cents).toBe(0);
  });

  test('COL_014: write_off fails when remaining due > $200 (ERR_WRITE_OFF_NOT_ALLOWED)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract(1);
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountCents: 25_000 });

    await advanceToPeriod(workspaceId, 4);
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.collections_stage).toBe('COLLECTIONS');
    expect(inv.amount_due_cents).toBe(25_000);

    const res = await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/write_off`, {}, 'SellerAR');
    await expectErrorCode(res, 'ERR_WRITE_OFF_NOT_ALLOWED');
  });

  test('COL_016: write_off fails when invoice has an active dispute (ERR_INVOICE_HAS_DISPUTE)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract(1);
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountCents: 15_000 });

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const lineId = getFirstInvoiceLineId(inv0);
    await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: 1000 }] },
      'BuyerAP'
    );

    await advanceToPeriod(workspaceId, 4);
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.collections_stage).toBe('COLLECTIONS');

    const res = await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/write_off`, {}, 'SellerAR');
    await expectErrorCode(res, 'ERR_INVOICE_HAS_DISPUTE');
  });

  test('INV_031: finance charge customer-level $500 ceiling scales and allocates leftover cents deterministically', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract(1);

    const i1 = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountCents: 1_333_334 });
    const i2 = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountCents: 1_333_334 });
    const i3 = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountCents: 1_333_334 });

    await advanceToPeriod(workspaceId, 2);
    const before = await getCustomer(workspaceId, customerId, 'SellerAdmin');

    const out = await triggerFinanceCharges(workspaceId);
    const ids: string[] = out.finance_charge_invoice_ids ?? [];
    expect(ids.length).toBe(3);

    const totals: number[] = [];
    for (const financeId of ids) {
      const f = await getInvoice(workspaceId, financeId, 'SellerAdmin');
      expect(f.type).toBe('FINANCE_CHARGE');
      expect(f.status).toBe('ACCEPTED');
      expect(f.issued_period_index).toBe(3);
      expect(f.delivered_period_index).toBe(3);
      expect(f.accepted_period_index).toBe(3);
      expect(f.due_period_index).toBe(4);
      expect(f.amount_due_cents).toBe(f.invoice_total_cents);

      totals.push(f.invoice_total_cents as number);
    }

    totals.sort((a, b) => a - b);
    expect(totals).toEqual([16_666, 16_667, 16_667]);
    const sum = totals.reduce((acc: number, n: number) => acc + n, 0);
    expect(sum).toBe(50_000);

    const after = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(after.balance_due_cents).toBe(before.balance_due_cents + 50_000);
  });

  test('INV_032: ceiling scaling can reduce below per-invoice $25 minimum (21 invoices)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract(1);

    const originals: string[] = [];
    for (let i = 0; i < 21; i++) {
      originals.push(await createAcceptedInvoice({ workspaceId, customerId, contractId, amountCents: 10_000 }));
    }
    originals.sort();

    await advanceToPeriod(workspaceId, 2);
    const before = await getCustomer(workspaceId, customerId, 'SellerAdmin');

    const out = await triggerFinanceCharges(workspaceId);
    const ids: string[] = out.finance_charge_invoice_ids ?? [];
    expect(ids.length).toBe(21);

    const totals: number[] = [];
    for (const financeId of ids) {
      const f = await getInvoice(workspaceId, financeId, 'SellerAdmin');
      expect(f.type).toBe('FINANCE_CHARGE');
      totals.push(f.invoice_total_cents as number);
    }

    totals.sort((a, b) => b - a);
    expect(totals.filter((n) => n === 2_381)).toHaveLength(20);
    expect(totals.filter((n) => n === 2_380)).toHaveLength(1);
    expect(totals.every((n) => n < 2_500)).toBe(true);
    expect(totals.reduce((acc, n) => acc + n, 0)).toBe(50_000);

    const after = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(after.balance_due_cents).toBe(before.balance_due_cents + 50_000);
  });

  test('INV_033: finance charge per-invoice max is $250 (25,000 cents)', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract(1);
    const invoiceId = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountCents: 10_000_000 });

    await advanceToPeriod(workspaceId, 2);
    const before = await getCustomer(workspaceId, customerId, 'SellerAdmin');

    const out = await triggerFinanceCharges(workspaceId);
    const ids: string[] = out.finance_charge_invoice_ids ?? [];
    expect(ids.length).toBe(1);

    const f = await getInvoice(workspaceId, ids[0], 'SellerAdmin');
    expect(f.type).toBe('FINANCE_CHARGE');
    expect(f.status).toBe('ACCEPTED');
    expect(f.invoice_total_cents).toBe(25_000);
    expect(f.amount_due_cents).toBe(25_000);

    const after = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(after.balance_due_cents).toBe(before.balance_due_cents + 25_000);
    expect(invoiceId).toBeDefined();
  });

  test('INV_301: finance-charge $500 ceiling scales across invoices and assigns leftover cent to lowest invoice_id', async () => {
    const workspace = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
    const workspaceId = workspace.workspace_id;
    const customer = await createCustomer(workspaceId, {}, 'SellerAdmin');
    const customerId = getCustomerId(customer);

    const contract = await createContract(
      workspaceId,
      customerId,
      {
        name: `K-${uniqueId('inv301')}`,
        payment_terms_periods: 1,
        requires_po: false,
        billing_cap_cents_per_period: 100_000_000
      },
      'SellerAdmin'
    );
    const contractId = getContractId(contract);
    await activateContract(workspaceId, contractId, 'SellerAdmin');

    const iBig1 = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountCents: 10_000_000 });
    const iBig2 = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountCents: 10_000_000 });
    const iBig3 = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountCents: 10_000_000 });
    const iSmall = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountCents: 100_000 });

    const originals = [iBig1, iBig2, iBig3, iSmall];
    const oldest = originals.slice().sort((a, b) => a.localeCompare(b))[0];
    const isBig = new Set([iBig1, iBig2, iBig3]);

    await advanceToPeriod(workspaceId, 2);
    const before = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    const bBefore = before.balance_due_cents as number;

    const out = await triggerFinanceCharges(workspaceId);
    const ids: string[] = out.finance_charge_invoice_ids ?? [];
    expect(out.period_index).toBe(3);
    expect(ids).toHaveLength(4);

    const totalsByRef: Record<string, number> = {};
    const seenRefs = new Set<string>();
    let sum = 0;

    for (const financeId of ids) {
      const f = await getInvoice(workspaceId, financeId, 'SellerAdmin');
      expect(f.type).toBe('FINANCE_CHARGE');
      expect(f.status).toBe('ACCEPTED');
      expect(f.issued_period_index).toBe(3);
      expect(f.delivered_period_index).toBe(3);
      expect(f.accepted_period_index).toBe(3);
      expect(f.due_period_index).toBe(4);
      expect(f.amount_due_cents).toBe(f.invoice_total_cents);

      const ref = f.reference_invoice_id as string;
      expect(typeof ref).toBe('string');
      expect(originals).toContain(ref);
      expect(seenRefs.has(ref)).toBe(false);
      seenRefs.add(ref);

      totalsByRef[ref] = f.invoice_total_cents as number;
      sum += f.invoice_total_cents as number;
    }

    for (const originalId of originals) {
      const base = isBig.has(originalId) ? 16_129 : 1_612;
      const expected = base + (originalId === oldest ? 1 : 0);
      expect(totalsByRef[originalId]).toBe(expected);
    }
    expect(sum).toBe(50_000);

    const after = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(after.balance_due_cents).toBe(bBefore + 50_000);
  });

  test('INV_201: finance-charge ceiling leftover cents are assigned by invoice_id tie-breaker', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract(1);

    const i1 = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountCents: 1_333_334 });
    const i2 = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountCents: 1_333_334 });
    const i3 = await createAcceptedInvoice({ workspaceId, customerId, contractId, amountCents: 1_333_334 });

    await advanceToPeriod(workspaceId, 2);
    const before = await getCustomer(workspaceId, customerId, 'SellerAdmin');

    const originalsSorted = [i1, i2, i3].slice().sort((a, b) => a.localeCompare(b));
    const [iLow, iMid, iHigh] = originalsSorted;
    const expectedByRef: Record<string, number> = {
      [iLow]: 16_667,
      [iMid]: 16_667,
      [iHigh]: 16_666
    };

    const out = await triggerFinanceCharges(workspaceId);
    const ids: string[] = out.finance_charge_invoice_ids ?? [];
    expect(out.period_index).toBe(3);
    expect(ids).toHaveLength(3);

    const totals: number[] = [];
    const seenRefs = new Set<string>();

    for (const financeId of ids) {
      const f = await getInvoice(workspaceId, financeId, 'SellerAdmin');
      expect(f.type).toBe('FINANCE_CHARGE');
      expect(f.status).toBe('ACCEPTED');
      expect(f.issued_period_index).toBe(3);
      expect(f.delivered_period_index).toBe(3);
      expect(f.accepted_period_index).toBe(3);
      expect(f.due_period_index).toBe(4);
      expect(f.amount_due_cents).toBe(f.invoice_total_cents);

      const ref = f.reference_invoice_id as string;
      expect(typeof ref).toBe('string');
      expect(Object.keys(expectedByRef)).toContain(ref);
      expect(seenRefs.has(ref)).toBe(false);
      seenRefs.add(ref);

      expect(f.invoice_total_cents).toBe(expectedByRef[ref]);
      totals.push(f.invoice_total_cents as number);
    }

    expect(seenRefs.size).toBe(3);
    expect(totals.reduce((acc: number, n: number) => acc + n, 0)).toBe(50_000);

    const after = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(after.balance_due_cents).toBe(before.balance_due_cents + 50_000);
  });

  test('TRANS_011: default payment_terms_periods=2 drives due_period_index and finance-charge issuance at first overdue close', async () => {
    const ws = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
    const workspaceId = ws.workspace_id;
    const customer = await createCustomer(workspaceId, {}, 'SellerAdmin');
    const customerId = getCustomerId(customer);

    const contractRes = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/contracts`,
      { name: `K-DEFAULT`, requires_po: false, billing_cap_cents_per_period: 10_000_000 },
      'SellerAdmin'
    );
    expectSuccess(contractRes);
    const contract = contractRes.body?.data ?? contractRes.body;
    const contractId = getContractId(contract);
    await activateContract(workspaceId, contractId, 'SellerAdmin');

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `TRANS011` }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { description: 'Line', quantity_units: 10, unit_price_cents: 10_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const invPre = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invPre.due_period_index).toBe(2);
    expect(invPre.collections_stage).toBe('CURRENT');

    const financePre = await listInvoices(workspaceId, { customer_id: customerId, type: 'FINANCE_CHARGE' }, 'SellerAdmin');
    expect(financePre).toHaveLength(0);

    const out0 = await triggerFinanceCharges(workspaceId);
    const ids0: string[] = out0.finance_charge_invoice_ids ?? [];
    expect(out0.period_index).toBe(3);
    expect(ids0).toHaveLength(0);

    const invAfter0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter0.status).toBe('ACCEPTED');
    expect(invAfter0.accepted_period_index).toBe(0);
    expect(invAfter0.due_period_index).toBe(2);
    expect(invAfter0.collections_stage).toBe('REMINDER');

    const before = await getCustomer(workspaceId, customerId, 'SellerAdmin');

    const out1 = await triggerFinanceCharges(workspaceId);
    const ids: string[] = out1.finance_charge_invoice_ids ?? [];
    expect(out1.period_index).toBe(4);
    expect(ids).toHaveLength(1);

    const f = await getInvoice(workspaceId, ids[0], 'SellerAdmin');
    expect(f.type).toBe('FINANCE_CHARGE');
    expect(f.status).toBe('ACCEPTED');
    expect(f.issued_period_index).toBe(4);
    expect(f.due_period_index).toBe(5);
    expect(f.invoice_total_cents).toBe(2_500);
    expect(f.amount_due_cents).toBe(2_500);

    const after = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(after.balance_due_cents).toBe(before.balance_due_cents + 2_500);
  });

  test('TRANS_017: credit applied before period close reduces finance charge base and amount', async () => {
    const { workspaceId, customerId, contractId } = await setupWorkspaceCustomerContract(1);

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `T17-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { description: 'Line', quantity_units: 1, unit_price_cents: 500_000 }, 'SellerAR');
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const inv2 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv2.collections_stage).toBe('REMINDER');
    const lineId = getFirstInvoiceLineId(inv2);

    const cm = await createCreditMemo(
      workspaceId,
      customerId,
      { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: lineId, quantity_units: 1, unit_price_cents: 100_000 }] },
      'SellerAR'
    );
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAR');
    await applyCreditMemo(workspaceId, cmId, invoiceId, 'SellerAR');

    const invAfterCredit = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfterCredit.amount_due_cents).toBe(400_000);
    expect(invAfterCredit.amount_disputed_cents).toBe(0);

    const snap = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(snap.balance_due_cents).toBe(400_000);

    const out = await triggerFinanceCharges(workspaceId);
    const ids: string[] = out.finance_charge_invoice_ids ?? [];
    expect(out.period_index).toBe(3);
    expect(ids).toHaveLength(1);

    const f = await getInvoice(workspaceId, ids[0], 'SellerAdmin');
    expect(f.type).toBe('FINANCE_CHARGE');
    expect(f.status).toBe('ACCEPTED');
    expect(f.issued_period_index).toBe(3);
    expect(f.delivered_period_index).toBe(3);
    expect(f.accepted_period_index).toBe(3);
    expect(f.due_period_index).toBe(4);
    expect(f.invoice_total_cents).toBe(6_000);
    expect(f.amount_due_cents).toBe(6_000);

    const inv3 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv3.amount_due_cents).toBe(400_000);
    expect(inv3.collections_stage).toBe('FINAL_NOTICE');

    const custAfter = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custAfter.balance_due_cents).toBe(406_000);
    expect(custAfter.unapplied_cash_cents).toBe(0);
    expect(custAfter.available_credit_cents).toBe(0);
  });
});
