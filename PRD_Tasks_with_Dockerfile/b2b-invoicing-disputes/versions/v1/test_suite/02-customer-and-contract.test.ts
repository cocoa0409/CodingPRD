import { postAs } from '../../../test-helpers/api-client';
import { expectErrorCode, expectSuccess } from '../../../test-helpers/assertions';
import { advanceToPeriod } from '../../../test-helpers/fixtures';
import {
  acceptInvoice,
  activateContract,
  addInvoiceLine,
  advancePeriod,
  closeCustomer,
  createContract,
  createCreditMemo,
  createCustomer,
  createDispute,
  createInvoice,
  createPayment,
  createWorkspace,
  finalizeInvoice,
  freezeCustomer,
  getContract,
  getContractId,
  getCreditMemoId,
  getCustomer,
  getCustomerId,
  getDispute,
  getDisputeId,
  getFirstInvoiceLineId,
  getInvoice,
  getInvoiceId,
  getWorkspace,
  getPaymentId,
  issueCreditMemo,
  markPaymentCleared,
  reversePayment,
  suspendContract,
  terminateContract,
  unfreezeCustomer,
  uniqueId,
  withdrawDispute
} from '../../../test-helpers/resources';

describe('Customer and Contract Tests', () => {
  async function setupWorkspaceCustomer() {
    const workspace = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
    const workspaceId = workspace.workspace_id;
    const customer = await createCustomer(workspaceId, { credit_limit_cents: 5_000_000 }, 'SellerAdmin');
    const customerId = getCustomerId(customer);
    return { workspaceId, customerId };
  }

  async function setupActiveContract(workspaceId: string, customerId: string, overrides?: Partial<{ payment_terms_periods: number; requires_po: boolean; billing_cap_cents_per_period: number }>) {
    const contract = await createContract(
      workspaceId,
      customerId,
      {
        name: `Contract-${uniqueId('ctr')}`,
        payment_terms_periods: overrides?.payment_terms_periods ?? 2,
        requires_po: overrides?.requires_po ?? false,
        billing_cap_cents_per_period: overrides?.billing_cap_cents_per_period ?? 10_000_000
      },
      'SellerAdmin'
    );
    const contractId = getContractId(contract);
    await activateContract(workspaceId, contractId, 'SellerAdmin');
    return { contractId };
  }

  async function createSentInvoice(workspaceId: string, customerId: string, contractId: string, totalCents: number) {
    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);

    if (totalCents % 10_000 !== 0) {
      throw new Error(`Test helper requires totalCents divisible by 10000. Got: ${totalCents}`);
    }
    const quantityUnits = totalCents / 10_000;
    await addInvoiceLine(workspaceId, invoiceId, {
      description: `Line-${uniqueId('inv')}`,
      quantity_units: quantityUnits,
      unit_price_cents: 10_000
    });

    await finalizeInvoice(workspaceId, invoiceId, { final_invoice: false }, 'SellerAR');
    await postAs(`/workspaces/${workspaceId}/invoices/${invoiceId}/send`, {}, 'SellerAR').then(expectSuccess);
    return invoiceId;
  }

  async function createAndAcceptInvoice(workspaceId: string, customerId: string, contractId: string, totalCents: number) {
    const invoiceId = await createSentInvoice(workspaceId, customerId, contractId, totalCents);
    const acceptRes = await acceptInvoice(workspaceId, invoiceId, 'BuyerAP');
    expectSuccess(acceptRes);
    return invoiceId;
  }

  test('CC_001: creating customer yields ACTIVE + zeroed balances', async () => {
    const workspace = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');

    const res = await postAs(
      `/workspaces/${workspace.workspace_id}/customers`,
      { display_name: `Globex-${uniqueId('globex')}`, external_customer_ref: `GLOBEX-${uniqueId('ref')}`, credit_limit_cents: 5_000_000 },
      'SellerAdmin'
    );
    expectSuccess(res);
    const c = res.body?.data ?? res.body;
    expect(c.status).toBe('ACTIVE');
    expect(c.balance_due_cents).toBe(0);
    expect(c.unapplied_cash_cents).toBe(0);
    expect(c.available_credit_cents).toBe(0);
  });

  test('CC_002: cannot close customer with available credits', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();

    const creditMemo = await createCreditMemo(
      workspaceId,
      customerId,
      {
        reason: 'GOODWILL',

        items: [{ quantity_units: 1, unit_price_cents: 5000 }]
      },
      'SellerAR'
    );
    const creditMemoId = getCreditMemoId(creditMemo);
    await issueCreditMemo(workspaceId, creditMemoId, 'SellerAR');

    const res = await closeCustomer(workspaceId, customerId, 'SellerAdmin');
    await expectErrorCode(res, 'ERR_CUSTOMER_NOT_SETTLED');
  });

  test('CC_003: can close customer when ledger is clean', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId);

    const invoiceId = await createAndAcceptInvoice(workspaceId, customerId, contractId, 100_000);
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const due = inv.amount_due_cents as number;

    const payment = await createPayment(workspaceId, customerId, { amount_cents: due, allocations: [{ invoice_id: invoiceId, amount_cents: due }] }, 'BuyerAP');
    await markPaymentCleared(workspaceId, getPaymentId(payment), 'SellerAR');

    const custBefore = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custBefore.balance_due_cents).toBe(0);
    expect(custBefore.unapplied_cash_cents).toBe(0);
    expect(custBefore.available_credit_cents).toBe(0);

    const res = await closeCustomer(workspaceId, customerId, 'SellerAdmin');
    expectSuccess(res);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('CLOSED');
  });

  test('CC_004: cannot create invoices for CLOSED customer', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId);

    const invoiceId = await createAndAcceptInvoice(workspaceId, customerId, contractId, 100_000);
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const due = inv.amount_due_cents as number;
    const payment = await createPayment(workspaceId, customerId, { amount_cents: due, allocations: [{ invoice_id: invoiceId, amount_cents: due }] }, 'BuyerAP');
    await markPaymentCleared(workspaceId, getPaymentId(payment), 'SellerAR');
    await closeCustomer(workspaceId, customerId, 'SellerAdmin').then(expectSuccess);

    const res = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/invoices`,
      { contract_id: contractId, external_invoice_ref: `INV-${uniqueId('erp')}` },
      'SellerAR'
    );
    await expectErrorCode(res, 'ERR_CUSTOMER_CLOSED');
  });

  test('TRANS_012: finalizing a DRAFT invoice after customer is CLOSED fails ERR_CUSTOMER_CLOSED', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId, { requires_po: false, payment_terms_periods: 2 });

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `T12-${uniqueId('inv')}` }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { description: 'Line', quantity_units: 1, unit_price_cents: 10_000 }, 'SellerAR');

    const draft = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(draft.status).toBe('DRAFT');
    expect(draft.invoice_total_cents).toBe(0);

    await closeCustomer(workspaceId, customerId, 'SellerAdmin').then(expectSuccess);
    const closed = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(closed.status).toBe('CLOSED');
    expect(closed.balance_due_cents).toBe(0);
    expect(closed.unapplied_cash_cents).toBe(0);
    expect(closed.available_credit_cents).toBe(0);

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/finalize`,
      { override_hold: false, override_billing_cap: false, final_invoice: false },
      'SellerAR'
    );
    await expectErrorCode(res, 'ERR_CUSTOMER_CLOSED');

    const invAfter = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfter.status).toBe('DRAFT');
    expect(invAfter.invoice_total_cents).toBe(0);
    expect(invAfter.issued_period_index == null).toBe(true);

    const custAfter = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custAfter.status).toBe('CLOSED');
    expect(custAfter.balance_due_cents).toBe(0);
    expect(custAfter.unapplied_cash_cents).toBe(0);
    expect(custAfter.available_credit_cents).toBe(0);
  });

  test('CC_005: activate contract moves status to ACTIVE', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();

    const contract = await createContract(workspaceId, customerId, { name: `MSA-${uniqueId('msa')}` }, 'SellerAdmin');
    const contractId = getContractId(contract);

    await activateContract(workspaceId, contractId, 'SellerAdmin');

    const got = await getContract(workspaceId, contractId, 'SellerAdmin');
    expect(got.status).toBe('ACTIVE');
  });

  test('CC_006: activating an already ACTIVE contract fails ERR_INVALID_STATE_TRANSITION', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const contract = await createContract(workspaceId, customerId, { name: `MSA-${uniqueId('msa')}` }, 'SellerAdmin');
    const contractId = getContractId(contract);
    await activateContract(workspaceId, contractId, 'SellerAdmin');

    const res = await postAs(`/workspaces/${workspaceId}/contracts/${contractId}/activate`, {}, 'SellerAdmin');
    await expectErrorCode(res, 'ERR_INVALID_STATE_TRANSITION');
  });

  test('CC_007: suspend contract moves status to SUSPENDED', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId);

    await suspendContract(workspaceId, contractId, 'SellerAdmin');
    const got = await getContract(workspaceId, contractId, 'SellerAdmin');
    expect(got.status).toBe('SUSPENDED');
  });

  test('CC_008: cannot finalize invoice under SUSPENDED contract unless final true-up', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId);
    await suspendContract(workspaceId, contractId, 'SellerAdmin');

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 10_000 });

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/finalize`,
      { override_hold: false, override_billing_cap: false, final_invoice: false },
      'SellerAR'
    );
    await expectErrorCode(res, 'ERR_CONTRACT_INACTIVE');
  });

  test('CC_009: SellerAdmin can finalize final true-up invoice under SUSPENDED contract when <= $2000', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId);
    await suspendContract(workspaceId, contractId, 'SellerAdmin');

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 15, unit_price_cents: 10_000 });

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/finalize`,
      { override_hold: false, override_billing_cap: false, final_invoice: true },
      'SellerAdmin'
    );
    expectSuccess(res);
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('FINALIZED');
  });

  test('CC_010: can create draft invoice for TERMINATED contract (finalize will fail later)', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId);
    await terminateContract(workspaceId, contractId, 'SellerAdmin');

    const res = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/invoices`,
      { contract_id: contractId, external_invoice_ref: `INV-${uniqueId('erp')}` },
      'SellerAR'
    );
    expectSuccess(res);
    const inv = res.body?.data ?? res.body;
    expect(inv.status).toBe('DRAFT');
  });

  test('CC_011: billing cap blocks finalizing invoice that would exceed cap in period', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId, { billing_cap_cents_per_period: 10_000_000 });

    const i1 = await createInvoice(workspaceId, customerId, { contract_id: contractId }, 'SellerAR');
    const i1Id = getInvoiceId(i1);
    await addInvoiceLine(workspaceId, i1Id, { quantity_units: 600, unit_price_cents: 10_000 });
    await finalizeInvoice(workspaceId, i1Id, {}, 'SellerAR');

    const i2 = await createInvoice(workspaceId, customerId, { contract_id: contractId }, 'SellerAR');
    const i2Id = getInvoiceId(i2);
    await addInvoiceLine(workspaceId, i2Id, { quantity_units: 500, unit_price_cents: 10_000 });

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${i2Id}/finalize`,
      { override_hold: false, override_billing_cap: false, final_invoice: false },
      'SellerAR'
    );
    await expectErrorCode(res, 'ERR_BILLING_CAP_EXCEEDED');
  });

  test('CC_012: SellerAdmin can override billing cap on finalize', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId, { billing_cap_cents_per_period: 10_000_000 });

    const i1 = await createInvoice(workspaceId, customerId, { contract_id: contractId }, 'SellerAR');
    const i1Id = getInvoiceId(i1);
    await addInvoiceLine(workspaceId, i1Id, { quantity_units: 600, unit_price_cents: 10_000 });
    await finalizeInvoice(workspaceId, i1Id, {}, 'SellerAR');

    const i2 = await createInvoice(workspaceId, customerId, { contract_id: contractId }, 'SellerAR');
    const i2Id = getInvoiceId(i2);
    await addInvoiceLine(workspaceId, i2Id, { quantity_units: 500, unit_price_cents: 10_000 });

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${i2Id}/finalize`,
      { override_hold: false, override_billing_cap: true, final_invoice: false },
      'SellerAdmin'
    );
    expectSuccess(res);
    const inv = await getInvoice(workspaceId, i2Id, 'SellerAdmin');
    expect(inv.status).toBe('FINALIZED');
  });

  test('CC_013: undisputed overdue exposure > $25k puts customer on CREDIT_HOLD', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId, { payment_terms_periods: 2 });

    const invoiceId = await createAndAcceptInvoice(workspaceId, customerId, contractId, 3_000_000);
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const duePeriod = inv.due_period_index as number;

    await advanceToPeriod(workspaceId, duePeriod + 1);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('CREDIT_HOLD');
  });

  test('CC_014: fully disputed large invoice does not trigger CREDIT_HOLD', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId, { payment_terms_periods: 2 });

    const invoiceId = await createAndAcceptInvoice(workspaceId, customerId, contractId, 2_600_000);
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);

    const duePeriod = inv.due_period_index as number;
    await advanceToPeriod(workspaceId, duePeriod);

    await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: invoiceLineId, disputed_units: 260 }] },
      'BuyerAP'
    );

    const invDisputed = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invDisputed.amount_disputed_cents).toBe(invDisputed.amount_due_cents);

    await advanceToPeriod(workspaceId, duePeriod + 1);

    const invOverdue = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invOverdue.collections_stage).toBe('CURRENT');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('ACTIVE');
  });

  test('INV_901: CREDIT_HOLD uses undisputed overdue exposure (partial dispute can keep customer ACTIVE)', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId, { payment_terms_periods: 1 });

    const invoiceId = await createAndAcceptInvoice(workspaceId, customerId, contractId, 3_000_000);

    await advanceToPeriod(workspaceId, 1);
    const inv1 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const lineId = getFirstInvoiceLineId(inv1);

    const dispute = await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'SERVICE_QUALITY', items: [{ invoice_line_id: lineId, disputed_amount_cents: 600_000 }] },
      'BuyerAP'
    );
    const disputeId = getDisputeId(dispute);

    const invAfterDispute = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invAfterDispute.amount_disputed_cents).toBe(600_000);

    await advanceToPeriod(workspaceId, 2);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('ACTIVE');

    expect(cust.balance_due_cents).toBe(3_000_000);

    const invOverdue = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invOverdue.amount_due_cents).toBe(3_000_000);
    expect(invOverdue.amount_disputed_cents).toBe(600_000);
    expect(invOverdue.collections_stage).toBe('REMINDER');

    const d = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(d.status).toBe('OPEN');
  });

  test('CC_015: reversing a cleared payment freezes the customer', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId);

    const invoiceId = await createAndAcceptInvoice(workspaceId, customerId, contractId, 100_000);
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const due = inv.amount_due_cents as number;

    const payment = await createPayment(workspaceId, customerId, { amount_cents: due, allocations: [{ invoice_id: invoiceId, amount_cents: due }] }, 'BuyerAP');
    const paymentId = getPaymentId(payment);
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');

    const rev = await reversePayment(workspaceId, paymentId, 'SellerAdmin');
    expectSuccess(rev);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('FROZEN');
  });

  test('CC_016: reversal freeze clears after two successful period advances (if no other holds)', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();

    const payment = await createPayment(workspaceId, customerId, { amount_cents: 50_000 }, 'BuyerAP');
    const paymentId = getPaymentId(payment);
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');
    await reversePayment(workspaceId, paymentId, 'SellerAdmin').then(expectSuccess);

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('ACTIVE');
  });

  test('CC_017: cannot unfreeze after fraud dispute closure with only one period advance', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId);

    const invoiceId = await createSentInvoice(workspaceId, customerId, contractId, 100_000);
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);

    const dispute = await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'FRAUD', items: [{ invoice_line_id: invoiceLineId, disputed_units: 1 }] },
      'BuyerAP'
    );
    const disputeId = getDisputeId(dispute);

    const frozen = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(frozen.status).toBe('FROZEN');

    const withdrawn = await withdrawDispute(workspaceId, disputeId, 'BuyerAP');
    expect(withdrawn.status).toBe('WITHDRAWN');

    await advancePeriod(workspaceId, 'System');

    const stillFrozen = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(stillFrozen.status).toBe('FROZEN');

    const res = await unfreezeCustomer(workspaceId, customerId, 'SellerAdmin');
    await expectErrorCode(res, 'ERR_CUSTOMER_STILL_FROZEN');
  });

  test('CC_018: manual freeze can be undone via unfreeze when no other freeze conditions apply', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    await freezeCustomer(workspaceId, customerId, 'MANUAL', 'SellerAdmin').then(expectSuccess);

    const res = await unfreezeCustomer(workspaceId, customerId, 'SellerAdmin');
    expectSuccess(res);
    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('ACTIVE');
  });

  test('TRANS_015: manual freeze persists across period closes and blocks BuyerAP payments until unfreeze', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();

    await freezeCustomer(workspaceId, customerId, 'MANUAL', 'SellerAdmin').then(expectSuccess);
    const frozen0 = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(frozen0.status).toBe('FROZEN');

    await advancePeriod(workspaceId, 'System');
    await advancePeriod(workspaceId, 'System');

    const ws = await getWorkspace(workspaceId, 'SellerAdmin');
    expect(ws.period_index).toBe(2);

    const res = await postAs(`/workspaces/${workspaceId}/customers/${customerId}/payments`, { amount_cents: 1_000 }, 'BuyerAP');
    await expectErrorCode(res, 'ERR_CUSTOMER_FROZEN');

    const frozen = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(frozen.status).toBe('FROZEN');
    expect(frozen.balance_due_cents).toBe(0);
    expect(frozen.unapplied_cash_cents).toBe(0);
    expect(frozen.available_credit_cents).toBe(0);
  });

  test('CC_019: customer returns to ACTIVE when overdue exposure < $5k and no collections/escalations', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId, { payment_terms_periods: 2 });

    const invoiceId = await createAndAcceptInvoice(workspaceId, customerId, contractId, 3_000_000);
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const duePeriod = inv.due_period_index as number;
    await advanceToPeriod(workspaceId, duePeriod + 1);

    const custHold = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custHold.status).toBe('CREDIT_HOLD');

    const invOverdue = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const dueNow = invOverdue.amount_due_cents as number;
    const targetRemaining = 400_000;
    const payAmount = dueNow - targetRemaining;

    const payment = await createPayment(
      workspaceId,
      customerId,
      { amount_cents: payAmount, allocations: [{ invoice_id: invoiceId, amount_cents: payAmount }] },
      'BuyerAP'
    );
    await markPaymentCleared(workspaceId, getPaymentId(payment), 'SellerAR');

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.status).toBe('ACTIVE');
  });

  test('CC_020: invoice in COLLECTIONS causes credit hold for new billing (finalize blocked)', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId, { payment_terms_periods: 1 });

    const invoiceId = await createAndAcceptInvoice(workspaceId, customerId, contractId, 100_000);
    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const duePeriod = inv.due_period_index as number;

    await advanceToPeriod(workspaceId, duePeriod + 3);
    const invNow = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(invNow.collections_stage).toBe('COLLECTIONS');

    const i2 = await createInvoice(workspaceId, customerId, { contract_id: contractId }, 'SellerAR');
    const i2Id = getInvoiceId(i2);
    await addInvoiceLine(workspaceId, i2Id, { quantity_units: 10, unit_price_cents: 10_000 });

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${i2Id}/finalize`,
      { override_hold: false, override_billing_cap: false, final_invoice: false },
      'SellerAR'
    );
    await expectErrorCode(res, 'ERR_CUSTOMER_ON_HOLD');
  });

  test('CC_021: frozen customer cannot create purchase orders (BuyerAP)', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();

    const payment = await createPayment(workspaceId, customerId, { amount_cents: 50_000 }, 'BuyerAP');
    const paymentId = getPaymentId(payment);
    await markPaymentCleared(workspaceId, paymentId, 'SellerAR');
    await reversePayment(workspaceId, paymentId, 'SellerAdmin').then(expectSuccess);

    const res = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/purchase_orders`,
      { po_number: `PO-${uniqueId('po')}`, lines: [{ description: 'Widgets', ordered_units: 10, unit_price_cents: 10_000, is_service: false }] },
      'BuyerAP'
    );
    await expectErrorCode(res, 'ERR_CUSTOMER_FROZEN');
  });

  test('CC_022: credit hold blocks invoice finalization for SellerAR', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId, { payment_terms_periods: 2 });

    const bigInvoiceId = await createAndAcceptInvoice(workspaceId, customerId, contractId, 3_000_000);
    const bigInv = await getInvoice(workspaceId, bigInvoiceId, 'SellerAdmin');
    await advanceToPeriod(workspaceId, (bigInv.due_period_index as number) + 1);

    const custHold = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(custHold.status).toBe('CREDIT_HOLD');

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 150, unit_price_cents: 10_000 });

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/finalize`,
      { override_hold: false, override_billing_cap: false, final_invoice: false },
      'SellerAR'
    );
    await expectErrorCode(res, 'ERR_CUSTOMER_ON_HOLD');
  });

  test('CC_023: SellerAdmin can override credit hold for <= $10k invoice when no collections invoices', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId, { payment_terms_periods: 2 });

    const bigInvoiceId = await createAndAcceptInvoice(workspaceId, customerId, contractId, 3_000_000);
    const bigInv = await getInvoice(workspaceId, bigInvoiceId, 'SellerAdmin');
    await advanceToPeriod(workspaceId, (bigInv.due_period_index as number) + 1);

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 90, unit_price_cents: 10_000 });

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/finalize`,
      { override_hold: true, override_billing_cap: false, final_invoice: false },
      'SellerAdmin'
    );
    expectSuccess(res);
    const got = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(got.status).toBe('FINALIZED');
  });

  test('CC_024: hold override does not apply when customer has an invoice in COLLECTIONS', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId, { payment_terms_periods: 1 });

    const invId = await createAndAcceptInvoice(workspaceId, customerId, contractId, 100_000);
    const inv = await getInvoice(workspaceId, invId, 'SellerAdmin');
    await advanceToPeriod(workspaceId, (inv.due_period_index as number) + 3);
    const invNow = await getInvoice(workspaceId, invId, 'SellerAdmin');
    expect(invNow.collections_stage).toBe('COLLECTIONS');

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 90, unit_price_cents: 10_000 });

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/finalize`,
      { override_hold: true, override_billing_cap: false, final_invoice: false },
      'SellerAdmin'
    );
    await expectErrorCode(res, 'ERR_CUSTOMER_ON_HOLD');
  });

  test('CC_025: requires_po enforced at finalize time (draft create succeeds, finalize fails ERR_PO_REQUIRED)', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId, { requires_po: true });

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    expect(invoice.status).toBe('DRAFT');
    await addInvoiceLine(workspaceId, invoiceId, { quantity_units: 10, unit_price_cents: 10_000 });

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/finalize`,
      { override_hold: false, override_billing_cap: false, final_invoice: false },
      'SellerAR'
    );
    await expectErrorCode(res, 'ERR_PO_REQUIRED');
  });

  test('CC_026: when requires_po is false, can create draft invoice without PO', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId, { requires_po: false });

    const res = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/invoices`,
      { contract_id: contractId, external_invoice_ref: `INV-${uniqueId('erp')}` },
      'SellerAR'
    );
    expectSuccess(res);
    const inv = res.body?.data ?? res.body;
    expect(inv.status).toBe('DRAFT');
  });

  test('TRANS_002: billing cap is evaluated per period (advancing period resets the cap window)', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId, { billing_cap_cents_per_period: 10_000_000 });

    const i0 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `I0-${uniqueId('i0')}` }, 'SellerAR');
    const i0Id = getInvoiceId(i0);
    await addInvoiceLine(workspaceId, i0Id, { quantity_units: 900, unit_price_cents: 10_000 });
    await finalizeInvoice(workspaceId, i0Id, {}, 'SellerAR');
    const inv0 = await getInvoice(workspaceId, i0Id, 'SellerAdmin');
    expect(inv0.issued_period_index).toBe(0);

    await advancePeriod(workspaceId, 'System');

    const i1 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `I1-${uniqueId('i1')}` }, 'SellerAR');
    const i1Id = getInvoiceId(i1);
    await addInvoiceLine(workspaceId, i1Id, { quantity_units: 900, unit_price_cents: 10_000 });

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${i1Id}/finalize`,
      { override_hold: false, override_billing_cap: false, final_invoice: false },
      'SellerAR'
    );
    expectSuccess(res);

    const inv1 = await getInvoice(workspaceId, i1Id, 'SellerAdmin');
    expect(inv1.issued_period_index).toBe(1);
  });

  test('TRANS_003: final true-up invoice under SUSPENDED contract is allowed only once', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId);
    await suspendContract(workspaceId, contractId, 'SellerAdmin');

    const i1 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `T1-${uniqueId('t')}` }, 'SellerAR');
    const i1Id = getInvoiceId(i1);
    await addInvoiceLine(workspaceId, i1Id, { quantity_units: 15, unit_price_cents: 10_000 });
    const ok = await postAs(
      `/workspaces/${workspaceId}/invoices/${i1Id}/finalize`,
      { override_hold: false, override_billing_cap: false, final_invoice: true },
      'SellerAdmin'
    );
    expectSuccess(ok);
    const inv1 = await getInvoice(workspaceId, i1Id, 'SellerAdmin');
    expect(inv1.status).toBe('FINALIZED');

    const i2 = await createInvoice(workspaceId, customerId, { contract_id: contractId, external_invoice_ref: `T2-${uniqueId('t')}` }, 'SellerAR');
    const i2Id = getInvoiceId(i2);
    await addInvoiceLine(workspaceId, i2Id, { quantity_units: 15, unit_price_cents: 10_000 });

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${i2Id}/finalize`,
      { override_hold: false, override_billing_cap: false, final_invoice: true },
      'SellerAdmin'
    );
    await expectErrorCode(res, 'ERR_CONTRACT_INACTIVE');

    const inv2 = await getInvoice(workspaceId, i2Id, 'SellerAdmin');
    expect(inv2.status).toBe('DRAFT');
    expect(inv2.invoice_total_cents).toBe(0);

    const cust = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cust.balance_due_cents).toBe(inv1.invoice_total_cents);
  });

  test('DEEP_013: unfreeze fails until two advances after fraud dispute closure; reversal undoes unapplied cash created while frozen', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId);

    const invoiceId = await createAndAcceptInvoice(workspaceId, customerId, contractId, 10_000);
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

    const p = await createPayment(workspaceId, customerId, { amount_cents: 10_000 }, 'SellerAR');
    const pId = getPaymentId(p);
    await markPaymentCleared(workspaceId, pId, 'SellerAR');
    const cash1 = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cash1.unapplied_cash_cents).toBe(10_000);

    await reversePayment(workspaceId, pId, 'SellerAdmin').then(expectSuccess);
    const cash2 = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(cash2.unapplied_cash_cents).toBe(0);
    expect(cash2.status).toBe('FROZEN');

    await advancePeriod(workspaceId, 'System');

    await withdrawDispute(workspaceId, disputeId, 'BuyerAP');
    const d = await getDispute(workspaceId, disputeId, 'SellerAdmin');
    expect(d.status).toBe('WITHDRAWN');

    await advancePeriod(workspaceId, 'System');

    const res = await unfreezeCustomer(workspaceId, customerId, 'SellerAdmin');
    await expectErrorCode(res, 'ERR_CUSTOMER_STILL_FROZEN');
    const stillFrozen = await getCustomer(workspaceId, customerId, 'SellerAdmin');
    expect(stillFrozen.status).toBe('FROZEN');
    expect(stillFrozen.unapplied_cash_cents).toBe(0);
  });
});
