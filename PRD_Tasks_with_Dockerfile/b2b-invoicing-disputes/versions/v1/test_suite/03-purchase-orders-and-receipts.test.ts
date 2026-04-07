import { postAs } from '../../../test-helpers/api-client';
import { expectErrorCode, expectSuccess } from '../../../test-helpers/assertions';
import {
  acceptInvoice,
  acknowledgePurchaseOrder,
  addInvoiceLine,
  applyCreditMemo,
  cancelPurchaseOrder,
  closePurchaseOrder,
  createContract,
  createCreditMemo,
  createCustomer,
  createDispute,
  createInvoice,
  createPurchaseOrder,
  createWorkspace,
  finalizeInvoice,
  getContractId,
  getCreditMemoId,
  getCustomerId,
  getFirstInvoiceLineId,
  getFirstPurchaseOrderLineId,
  getInvoice,
  getInvoiceId,
  getPurchaseOrder,
  getPurchaseOrderId,
  issueCreditMemo,
  recordReceipt,
  sendInvoice,
  uniqueId
} from '../../../test-helpers/resources';

describe('Purchase Order and Receipt Tests', () => {
  async function setupWorkspaceCustomer() {
    const workspace = await createWorkspace({ currency: 'USD' }, 'SellerAdmin');
    const workspaceId = workspace.workspace_id;
    const customer = await createCustomer(workspaceId, {}, 'SellerAdmin');
    const customerId = getCustomerId(customer);
    return { workspaceId, customerId };
  }

  async function setupActiveContract(workspaceId: string, customerId: string, overrides?: Partial<{ requires_po: boolean }>) {
    const contract = await createContract(
      workspaceId,
      customerId,
      {
        name: `MSA-${uniqueId('msa')}`,
        payment_terms_periods: 2,
        requires_po: overrides?.requires_po ?? true,
        billing_cap_cents_per_period: 10_000_000
      },
      'SellerAdmin'
    );
    const contractId = getContractId(contract);
    await postAs(`/workspaces/${workspaceId}/contracts/${contractId}/activate`, {}, 'SellerAdmin').then(expectSuccess);
    return { contractId };
  }

  async function createInvoiceAgainstPoLine(params: {
    workspaceId: string;
    customerId: string;
    contractId: string;
    purchaseOrderId: string;
    purchaseOrderLineId: string;
    quantityUnits: number;
    unitPriceCents: number;
    finalize?: boolean;
    send?: boolean;
  }) {
    const invoice = await createInvoice(
      params.workspaceId,
      params.customerId,
      { contract_id: params.contractId, purchase_order_id: params.purchaseOrderId, external_invoice_ref: `INV-${uniqueId('ext')}` },
      'SellerAR'
    );
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(params.workspaceId, invoiceId, {
      description: `Widgets-${uniqueId('w')}`,
      quantity_units: params.quantityUnits,
      unit_price_cents: params.unitPriceCents,
      purchase_order_line_id: params.purchaseOrderLineId
    });
    if (params.finalize ?? true) {
      await finalizeInvoice(params.workspaceId, invoiceId, {}, 'SellerAR');
    }
    if (params.send ?? true) {
      await sendInvoice(params.workspaceId, invoiceId, 'SellerAR');
    }
    return invoiceId;
  }

  test('PO_001: creating purchase order returns OPEN status', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { po_number: 'PO100', lines: [{ ordered_units: 10, unit_price_cents: 10000, is_service: false }] },
      'BuyerAP'
    );
    expect(po.status).toBe('OPEN');
  });

  test('PO_002: duplicate po_number while OPEN fails ERR_DUPLICATE_PO_NUMBER', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();

    const p1 = await createPurchaseOrder(
      workspaceId,
      customerId,
      { po_number: 'PO100', lines: [{ ordered_units: 10, unit_price_cents: 10000, is_service: false }] },
      'BuyerAP'
    );
    const p1Id = getPurchaseOrderId(p1);

    const res = await postAs(
      `/workspaces/${workspaceId}/customers/${customerId}/purchase_orders`,
      { po_number: 'PO100', lines: [{ description: 'Widgets', ordered_units: 10, unit_price_cents: 10000, is_service: false }] },
      'BuyerAP'
    );
    await expectErrorCode(res, 'ERR_DUPLICATE_PO_NUMBER');

    const po = await getPurchaseOrder(workspaceId, p1Id, 'SellerAdmin');
    expect(po.status).toBe('OPEN');
  });

  test('PO_003: po_number can be reused after PO is CLOSED', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();

    const po1 = await createPurchaseOrder(
      workspaceId,
      customerId,
      { po_number: 'PO100', lines: [{ ordered_units: 10, unit_price_cents: 10000, is_service: false }] },
      'BuyerAP'
    );
    const po1Id = getPurchaseOrderId(po1);
    await closePurchaseOrder(workspaceId, po1Id, 'BuyerAP').then(expectSuccess);
    const po1After = await getPurchaseOrder(workspaceId, po1Id, 'SellerAdmin');
    expect(po1After.status).toBe('CLOSED');

    const po2 = await createPurchaseOrder(
      workspaceId,
      customerId,
      { po_number: 'PO100', lines: [{ ordered_units: 5, unit_price_cents: 10000, is_service: false }] },
      'BuyerAP'
    );
    const po2Id = getPurchaseOrderId(po2);
    expect(po2Id).not.toBe(po1Id);
    const po2After = await getPurchaseOrder(workspaceId, po2Id, 'SellerAdmin');
    expect(po2After.status).toBe('OPEN');
  });

  test('PO_004: seller can acknowledge PO (ACKNOWLEDGED)', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 10, unit_price_cents: 10000, is_service: false }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);

    await acknowledgePurchaseOrder(workspaceId, poId, 'SellerAR');
    const got = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    expect(got.status).toBe('ACKNOWLEDGED');
  });

  test('PO_005: receipt up to 1% above ordered succeeds', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 100, unit_price_cents: 10000, is_service: false }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const lineId = getFirstPurchaseOrderLineId(poFull);

    const res = await recordReceipt(workspaceId, poId, [{ purchase_order_line_id: lineId, received_units: 101 }], 'BuyerAP');
    expectSuccess(res);

    const after = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    expect(after.lines[0].received_units).toBe(101);
  });

  test('PO_006: receipt beyond 1% tolerance fails ERR_RECEIPT_EXCEEDS_TOLERANCE', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 100, unit_price_cents: 10000, is_service: false }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const lineId = getFirstPurchaseOrderLineId(poFull);

    const res = await recordReceipt(workspaceId, poId, [{ purchase_order_line_id: lineId, received_units: 102 }], 'BuyerAP');
    await expectErrorCode(res, 'ERR_RECEIPT_EXCEEDS_TOLERANCE');

    const after = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    expect(after.lines[0].received_units).toBe(0);
  });

  test('PO_007: net_billed_units reflects invoiced units', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId, { requires_po: true });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 10, unit_price_cents: 10000, is_service: false }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const lineId = getFirstPurchaseOrderLineId(poFull);

    const invoiceId = await createInvoiceAgainstPoLine({
      workspaceId,
      customerId,
      contractId,
      purchaseOrderId: poId,
      purchaseOrderLineId: lineId,
      quantityUnits: 10,
      unitPriceCents: 10000,
      finalize: true,
      send: false
    });

    const got = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    expect(got.lines[0].net_billed_units).toBe(10);
    expect(invoiceId).toBeDefined();
  });

  test('PO_008: accepting invoice with quantity mismatch exception fails ERR_MATCH_EXCEPTION', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId, { requires_po: true });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 100, unit_price_cents: 10000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const lineId = getFirstPurchaseOrderLineId(poFull);

    const invoiceId = await createInvoiceAgainstPoLine({
      workspaceId,
      customerId,
      contractId,
      purchaseOrderId: poId,
      purchaseOrderLineId: lineId,
      quantityUnits: 103,
      unitPriceCents: 10000,
      finalize: true,
      send: true
    });

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('SENT');
    expect(inv.match_status).toBe('EXCEPTION');

    const res = await acceptInvoice(workspaceId, invoiceId, 'BuyerAP');
    await expectErrorCode(res, 'ERR_MATCH_EXCEPTION');
  });

  test('PO_009: match_status is MATCHED at exactly +2% quantity tolerance for services', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId, { requires_po: true });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 100, unit_price_cents: 10000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const lineId = getFirstPurchaseOrderLineId(poFull);

    const invoiceId = await createInvoiceAgainstPoLine({
      workspaceId,
      customerId,
      contractId,
      purchaseOrderId: poId,
      purchaseOrderLineId: lineId,
      quantityUnits: 102,
      unitPriceCents: 10000,
      finalize: true,
      send: true
    });

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.match_status).toBe('MATCHED');
  });

  test('PO_010: match_status is MATCHED when unit price is within +5% tolerance', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId, { requires_po: true });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 10, unit_price_cents: 10000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const lineId = getFirstPurchaseOrderLineId(poFull);

    const invoiceId = await createInvoiceAgainstPoLine({
      workspaceId,
      customerId,
      contractId,
      purchaseOrderId: poId,
      purchaseOrderLineId: lineId,
      quantityUnits: 10,
      unitPriceCents: 10499,
      finalize: true,
      send: true
    });

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.match_status).toBe('MATCHED');
  });

  test('PO_011: match_status is EXCEPTION when unit price exceeds +5% tolerance', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId, { requires_po: true });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 10, unit_price_cents: 10000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const lineId = getFirstPurchaseOrderLineId(poFull);

    const invoiceId = await createInvoiceAgainstPoLine({
      workspaceId,
      customerId,
      contractId,
      purchaseOrderId: poId,
      purchaseOrderLineId: lineId,
      quantityUnits: 10,
      unitPriceCents: 10600,
      finalize: true,
      send: true
    });

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.match_status).toBe('EXCEPTION');
  });

  test('PO_012: goods invoice with zero receipts cannot be accepted (ERR_MATCH_EXCEPTION)', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId, { requires_po: true });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 10, unit_price_cents: 10000, is_service: false }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const lineId = getFirstPurchaseOrderLineId(poFull);

    await recordReceipt(workspaceId, poId, [{ purchase_order_line_id: lineId, received_units: 0 }], 'BuyerAP').then(expectSuccess);

    const invoiceId = await createInvoiceAgainstPoLine({
      workspaceId,
      customerId,
      contractId,
      purchaseOrderId: poId,
      purchaseOrderLineId: lineId,
      quantityUnits: 10,
      unitPriceCents: 10000,
      finalize: true,
      send: true
    });

    const res = await acceptInvoice(workspaceId, invoiceId, 'BuyerAP');
    await expectErrorCode(res, 'ERR_MATCH_EXCEPTION');

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('SENT');
    expect(inv.match_status).toBe('EXCEPTION');
    expect(inv.accepted_period_index == null).toBe(true);
    expect(inv.due_period_index == null).toBe(true);
  });

  test('PO_013: buyer can accept goods invoice with match exceptions if non-matchable portion is fully disputed', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId, { requires_po: true });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 10, unit_price_cents: 10000, is_service: false }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const lineId = getFirstPurchaseOrderLineId(poFull);

    await recordReceipt(workspaceId, poId, [{ purchase_order_line_id: lineId, received_units: 0 }], 'BuyerAP').then(expectSuccess);

    const invoiceId = await createInvoiceAgainstPoLine({
      workspaceId,
      customerId,
      contractId,
      purchaseOrderId: poId,
      purchaseOrderLineId: lineId,
      quantityUnits: 10,
      unitPriceCents: 10000,
      finalize: true,
      send: true
    });

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);

    await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'MISSING_RECEIPT', items: [{ invoice_line_id: invoiceLineId, disputed_units: 10 }] },
      'BuyerAP'
    );

    const res = await acceptInvoice(workspaceId, invoiceId, 'BuyerAP');
    expectSuccess(res);

    const accepted = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(accepted.status).toBe('ACCEPTED');
  });

  test('PO_014: service lines do not require receipts; acceptance succeeds', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId, { requires_po: true });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 10, unit_price_cents: 10000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const lineId = getFirstPurchaseOrderLineId(poFull);

    const invoiceId = await createInvoiceAgainstPoLine({
      workspaceId,
      customerId,
      contractId,
      purchaseOrderId: poId,
      purchaseOrderLineId: lineId,
      quantityUnits: 10,
      unitPriceCents: 10000,
      finalize: true,
      send: true
    });

    const res = await acceptInvoice(workspaceId, invoiceId, 'BuyerAP');
    expectSuccess(res);

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).toBe('ACCEPTED');
    expect(inv.match_status).toBe('MATCHED');
  });

  test('PO_015: cannot cancel PO that has finalized invoices (ERR_PO_HAS_INVOICES)', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId, { requires_po: true });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 10, unit_price_cents: 10000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const lineId = getFirstPurchaseOrderLineId(poFull);

    await createInvoiceAgainstPoLine({
      workspaceId,
      customerId,
      contractId,
      purchaseOrderId: poId,
      purchaseOrderLineId: lineId,
      quantityUnits: 10,
      unitPriceCents: 10000,
      finalize: true,
      send: false
    });

    const res = await cancelPurchaseOrder(workspaceId, poId, 'BuyerAP');
    await expectErrorCode(res, 'ERR_PO_HAS_INVOICES');

    const poAfter = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    expect(poAfter.status).toBe('OPEN');
  });

  test('PO_016: can cancel OPEN PO with no invoices (status becomes CANCELLED)', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 10, unit_price_cents: 10000, is_service: false }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);

    const res = await cancelPurchaseOrder(workspaceId, poId, 'BuyerAP');
    expectSuccess(res);
    const got = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    expect(got.status).toBe('CANCELLED');
  });

  test('PO_017: accept succeeds when unreceived portion is disputed (goods)', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId, { requires_po: true });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 10, unit_price_cents: 10000, is_service: false }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const lineId = getFirstPurchaseOrderLineId(poFull);

    await recordReceipt(workspaceId, poId, [{ purchase_order_line_id: lineId, received_units: 5 }], 'BuyerAP').then(expectSuccess);

    const invoiceId = await createInvoiceAgainstPoLine({
      workspaceId,
      customerId,
      contractId,
      purchaseOrderId: poId,
      purchaseOrderLineId: lineId,
      quantityUnits: 10,
      unitPriceCents: 10000,
      finalize: true,
      send: true
    });

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.match_status).toBe('EXCEPTION');
    const invoiceLineId = getFirstInvoiceLineId(inv);

    await createDispute(
      workspaceId,
      invoiceId,
      { reason: 'MISSING_RECEIPT', items: [{ invoice_line_id: invoiceLineId, disputed_units: 5 }] },
      'BuyerAP'
    );

    const res = await acceptInvoice(workspaceId, invoiceId, 'BuyerAP');
    expectSuccess(res);
    const accepted = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(accepted.status).toBe('ACCEPTED');
  });

  test('PO_018: applying line-tied credit reduces PO net_billed_units', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId, { requires_po: true });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 10, unit_price_cents: 10000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const lineId = getFirstPurchaseOrderLineId(poFull);

    const invoiceId = await createInvoiceAgainstPoLine({
      workspaceId,
      customerId,
      contractId,
      purchaseOrderId: poId,
      purchaseOrderLineId: lineId,
      quantityUnits: 10,
      unitPriceCents: 10000,
      finalize: true,
      send: true
    });
    await acceptInvoice(workspaceId, invoiceId, 'BuyerAP').then(expectSuccess);

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    const invoiceLineId = getFirstInvoiceLineId(inv);

    const cm = await createCreditMemo(
      workspaceId,
      customerId,
      { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: invoiceLineId, quantity_units: 2, unit_price_cents: 10000 }] },
      'SellerAR'
    );
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAR');
    await applyCreditMemo(workspaceId, cmId, invoiceId, 'SellerAR');

    const poAfter = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    expect(poAfter.lines[0].net_billed_units).toBe(8);
  });

  test('PO_019: match_status can change to MATCHED after credits reduce net billed units', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId, { requires_po: true });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 10, unit_price_cents: 10000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const lineId = getFirstPurchaseOrderLineId(poFull);

    const invoiceId = await createInvoiceAgainstPoLine({
      workspaceId,
      customerId,
      contractId,
      purchaseOrderId: poId,
      purchaseOrderLineId: lineId,
      quantityUnits: 12,
      unitPriceCents: 10000,
      finalize: true,
      send: true
    });

    const inv0 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv0.match_status).toBe('EXCEPTION');
    const invoiceLineId = getFirstInvoiceLineId(inv0);

    const cm = await createCreditMemo(
      workspaceId,
      customerId,
      { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: invoiceLineId, quantity_units: 2, unit_price_cents: 10000 }] },
      'SellerAR'
    );
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAR');
    await applyCreditMemo(workspaceId, cmId, invoiceId, 'SellerAR');

    const inv1 = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv1.match_status).toBe('MATCHED');
  });

  test('PO_020: invoice line cannot reference PO line from different PO (ERR_INVALID_REQUEST)', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId, { requires_po: true });

    const p1 = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 10, unit_price_cents: 10000, is_service: true }] },
      'BuyerAP'
    );
    const p2 = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 10, unit_price_cents: 10000, is_service: true }] },
      'BuyerAP'
    );
    const p1Id = getPurchaseOrderId(p1);
    const p2Id = getPurchaseOrderId(p2);

    const p2Full = await getPurchaseOrder(workspaceId, p2Id, 'SellerAdmin');
    const p2LineId = getFirstPurchaseOrderLineId(p2Full);

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: p1Id }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);

    const res = await postAs(
      `/workspaces/${workspaceId}/invoices/${invoiceId}/lines`,
      { description: 'Widgets', quantity_units: 10, unit_price_cents: 10000, purchase_order_line_id: p2LineId },
      'SellerAR'
    );
    await expectErrorCode(res, 'ERR_INVALID_REQUEST');
  });

  test('PO_021: accept fails when invoice references an unreceived goods line not covered by dispute', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId, { requires_po: true });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      {
        lines: [
          { ordered_units: 10, unit_price_cents: 10000, is_service: false },
          { ordered_units: 10, unit_price_cents: 10000, is_service: false }
        ]
      },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const line1Id = poFull.lines[0].purchase_order_line_id ?? poFull.lines[0].id;
    const line2Id = poFull.lines[1].purchase_order_line_id ?? poFull.lines[1].id;
    if (!line1Id || !line2Id) throw new Error('Could not resolve PO line ids');

    await recordReceipt(workspaceId, poId, [{ purchase_order_line_id: line1Id, received_units: 10 }], 'BuyerAP').then(expectSuccess);

    const invoice = await createInvoice(workspaceId, customerId, { contract_id: contractId, purchase_order_id: poId }, 'SellerAR');
    const invoiceId = getInvoiceId(invoice);
    await addInvoiceLine(workspaceId, invoiceId, { description: 'L1', quantity_units: 10, unit_price_cents: 10000, purchase_order_line_id: line1Id });
    await addInvoiceLine(workspaceId, invoiceId, { description: 'L2', quantity_units: 10, unit_price_cents: 10000, purchase_order_line_id: line2Id });
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');

    const res = await acceptInvoice(workspaceId, invoiceId, 'BuyerAP');
    await expectErrorCode(res, 'ERR_MATCH_EXCEPTION');
  });

  test('PO_022: closing PO sets status CLOSED and does not void/change existing invoice', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId, { requires_po: true });

    const po = await createPurchaseOrder(
      workspaceId,
      customerId,
      { lines: [{ ordered_units: 10, unit_price_cents: 10000, is_service: true }] },
      'BuyerAP'
    );
    const poId = getPurchaseOrderId(po);
    const poFull = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    const lineId = getFirstPurchaseOrderLineId(poFull);

    const invoiceId = await createInvoiceAgainstPoLine({
      workspaceId,
      customerId,
      contractId,
      purchaseOrderId: poId,
      purchaseOrderLineId: lineId,
      quantityUnits: 10,
      unitPriceCents: 10000,
      finalize: true,
      send: true
    });

    await closePurchaseOrder(workspaceId, poId, 'BuyerAP').then(expectSuccess);
    const poAfter = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    expect(poAfter.status).toBe('CLOSED');

    const inv = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(inv.status).not.toBe('VOIDED');
  });

  test('PO_023: 1-cent line-tied credit can flip price match_status via floor effective-unit-price math', async () => {
    const { workspaceId, customerId } = await setupWorkspaceCustomer();
    const { contractId } = await setupActiveContract(workspaceId, customerId, { requires_po: true });

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
      { contract_id: contractId, purchase_order_id: poId, external_invoice_ref: `INV-${uniqueId('ext')}` },
      'SellerAR'
    );
    const invoiceId = getInvoiceId(invoice);

    await addInvoiceLine(
      workspaceId,
      invoiceId,
      { description: 'Svc', quantity_units: 3, unit_price_cents: 10_501, purchase_order_line_id: poLineId },
      'SellerAR'
    );
    await finalizeInvoice(workspaceId, invoiceId, {}, 'SellerAR');
    await sendInvoice(workspaceId, invoiceId, 'SellerAR');

    const before = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(before.match_status).toBe('EXCEPTION');
    const invoiceLineId = getFirstInvoiceLineId(before);

    const cm = await createCreditMemo(
      workspaceId,
      customerId,
      { invoice_id: invoiceId, reason: 'GOODWILL', items: [{ invoice_line_id: invoiceLineId, quantity_units: 1, unit_price_cents: 1 }] },
      'SellerAR'
    );
    const cmId = getCreditMemoId(cm);
    await issueCreditMemo(workspaceId, cmId, 'SellerAR');
    await applyCreditMemo(workspaceId, cmId, invoiceId, 'SellerAR');

    const after = await getInvoice(workspaceId, invoiceId, 'SellerAdmin');
    expect(after.match_status).toBe('MATCHED');

    const poAfter = await getPurchaseOrder(workspaceId, poId, 'SellerAdmin');
    expect(poAfter.lines[0].net_billed_units).toBe(2);
  });
});
