import {
  createWorkspace,
  createEvent,
  createPool,
  createOrder,
  getWorkspace,
  getEvent,
  getPool,
  getOrder,
  getAdmission,
  putEventOnSale,
  pauseEvent,
  closeEvent,
  cancelEvent,
  adjustPool,
  setOrderLines,
  submitOrder,
  approveOrder,
  payOrder,
  refundOrder,
  transferAdmission,
  uniqueId,
  Workspace,
  Event,
  Pool,
  Order,
  Admission,
} from './resources';

export interface FX_BASE_WS_Result {
  W: string;
  vW: string;
}

export interface FX_EVENT_DRAFT_WITH_POOLS_Result extends FX_BASE_WS_Result {
  E: string;
  vE: string;
  P_GA: string;
  P_VIP: string;
  P_FS: string;
  vPGA: string;
  vPVIP: string;
  vPFS: string;
}

export interface FX_EVENT_ONSALE_WITH_POOLS_Result extends FX_EVENT_DRAFT_WITH_POOLS_Result {
  vE2: string;
}

export interface FX_EVENT_PAUSED_WITH_POOLS_Result extends FX_EVENT_ONSALE_WITH_POOLS_Result {
  vE3: string;
}

export interface FX_EVENT_CLOSED_WITH_POOLS_Result extends FX_EVENT_ONSALE_WITH_POOLS_Result {
  vE4: string;
}

export interface FX_EVENT_CLOSED_WITH_ADMISSION_Result extends FX_EVENT_ONSALE_WITH_POOLS_Result {
  OC: string;
  vOC: string;
  vOC2: string;
  vOC3: string;
  AX: string;
  vAX: string;
  vE4b: string;
}

export interface FX_ORDER_DRAFT_U1_Result extends FX_EVENT_ONSALE_WITH_POOLS_Result {
  O: string;
  vO: string;
}

export interface FX_ORDER_DRAFT_U1_GA2_Result extends FX_ORDER_DRAFT_U1_Result {
  vO2: string;
}

export interface FX_ORDER_SUBMITTED_U1_GA2_Result extends FX_ORDER_DRAFT_U1_GA2_Result {
  vO3: string;
  vPGA2: string;
}

export interface FX_ORDER_PAID_U1_GA2_Result extends FX_ORDER_SUBMITTED_U1_GA2_Result {
  A1: string;
  A2: string;
  vO4: string;
  vPGA3: string;
}

export interface FX_ORDER_DRAFT_U1_VIP1_Result extends FX_ORDER_DRAFT_U1_Result {
  vO2: string;
}

export interface FX_ORDER_SUBMITTED_U1_VIP1_Result extends FX_ORDER_DRAFT_U1_VIP1_Result {
  vO3: string;
  vPVIP2: string;
}

export interface FX_ORDER_APPROVED_U1_VIP1_Result extends FX_ORDER_SUBMITTED_U1_VIP1_Result {
  vO4: string;
}

export interface FX_ORDER_PAID_U1_VIP1_Result extends FX_ORDER_APPROVED_U1_VIP1_Result {
  AV1: string;
  vO5: string;
}

export interface FX_ORDER_PAID_U1_FS1_Result extends FX_EVENT_ONSALE_WITH_POOLS_Result {
  O: string;
  vO: string;
  vO2: string;
  vO3: string;
  AF1: string;
  vO4: string;
}

export interface FX_ORDER_PAID_U1_MIXED_GA1_VIP1_Result extends FX_EVENT_ONSALE_WITH_POOLS_Result {
  O: string;
  vO: string;
  vO2: string;
  vO3: string;
  vO4: string;
  AM1: string;
  AM2: string;
  vO5: string;
}

export interface FX_EVENT_ONSALE_BOX_Result extends FX_BASE_WS_Result {
  EB: string;
  vEB: string;
  P_BOX: string;
  vEB2: string;
  vPBOX: string;
}

export interface FX_ORDER_SUBMITTED_U1_BOX2_Result extends FX_EVENT_ONSALE_BOX_Result {
  O: string;
  vO: string;
  vO2: string;
  vO3: string;
}

export interface FX_LIMIT_EVENT_ONSALE_Result extends FX_BASE_WS_Result {
  EL: string;
  vEL: string;
  PLGA: string;
  vEL2: string;
  vPLGA: string;
}

export interface FX_LIMIT_ORDER_PAID_U1_GA2_Result extends FX_LIMIT_EVENT_ONSALE_Result {
  O1: string;
  vO1: string;
  vO12: string;
  vO13: string;
  L1: string;
  L2: string;
  vO14: string;
}

export interface FX_LIMIT_ORDER_PAID_U2_GA2_Result extends FX_LIMIT_EVENT_ONSALE_Result {
  O2: string;
  vO2: string;
  vO22: string;
  vO23: string;
  L3: string;
  L4: string;
  vO24: string;
}

export interface FX_OVERALLOCATED_POOL_Result extends FX_BASE_WS_Result {
  EO: string;
  vEO: string;
  PTC: string;
  vEO2: string;
  O: string;
  vO: string;
  vO2: string;
  vPTC2: string;
  vPTC3: string;
  vW2: string;
}

export interface FX_CANCELLED_EVENT_WITH_PAID_Result extends FX_ORDER_PAID_U1_GA2_Result {
  vE5: string;
  vE6: string;
  vW2: string;
}

export interface FX_CANCELLED_EVENT_REMEDIED_Result extends FX_CANCELLED_EVENT_WITH_PAID_Result {
  vO5: string;
  vO6: string;
  vW3: string;
}

export interface FX_WS_TWO_EVENTS_HALT_WITH_SCANABLE_Result extends FX_BASE_WS_Result {
  E1: string;
  vE1: string;
  P1: string;
  E2: string;
  vE2: string;
  P2: string;
  O2: string;
  vO2: string;
  vO22: string;
  vO23: string;
  A2E2: string;
  O1: string;
  vO1: string;
  vO12: string;
  vO13: string;
  A1E1: string;
  vE1b: string;
  vW2: string;
  vA2: string;
}

export interface FX_WS_HALT_WITH_EXISTING_DRAFT_ORDER_Result extends FX_BASE_WS_Result {
  EH1: string;
  vEH1: string;
  PH1: string;
  EH2: string;
  vEH2: string;
  PH2: string;
  OH: string;
  vOH: string;
  OHP: string;
  vOHP: string;
  vOHP2: string;
  vOHP3: string;
  AHP1: string;
  vEH1b: string;
  vWH: string;
}

export async function FX_BASE_WS(): Promise<FX_BASE_WS_Result> {
  const workspace = await createWorkspace({ name: `TestWS-${uniqueId()}`, settlement_currency: 'USD' });
  const ws = await getWorkspace(workspace.id);

  return {
    W: workspace.id,
    vW: ws.version,
  };
}

export async function FX_EVENT_DRAFT_WITH_POOLS(): Promise<FX_EVENT_DRAFT_WITH_POOLS_Result> {
  const base = await FX_BASE_WS();

  const event = await createEvent(base.W, {
    title: 'Concert',
    starts_at_local: '2026-04-01T20:00',
    max_tickets_per_actor: 6,
  });
  const ev = await getEvent(base.W, event.id);

  const gaPool = await createPool(base.W, event.id, {
    label: 'GA',
    kind: 'STANDARD',
    price_cents: 5000,
    currency: 'USD',
    capacity_total: 10,
    holdback_qty: 2,
    refund_policy: 'REFUNDABLE',
    transfer_policy: 'OPEN',
    pool_holdings_limit: 6,
  });

  const vipPool = await createPool(base.W, event.id, {
    label: 'VIP',
    kind: 'PREMIUM',
    price_cents: 15000,
    currency: 'USD',
    capacity_total: 4,
    holdback_qty: 0,
    refund_policy: 'CREDIT_ONLY',
    transfer_policy: 'ONCE',
    pool_holdings_limit: 2,
  });

  const fsPool = await createPool(base.W, event.id, {
    label: 'FS',
    kind: 'STANDARD',
    price_cents: 7000,
    currency: 'USD',
    capacity_total: 2,
    holdback_qty: 0,
    refund_policy: 'FINAL_SALE',
    transfer_policy: 'NONE',
    pool_holdings_limit: 2,
  });

  const ga = await getPool(base.W, event.id, gaPool.id);
  const vip = await getPool(base.W, event.id, vipPool.id);
  const fs = await getPool(base.W, event.id, fsPool.id);

  return {
    ...base,
    E: event.id,
    vE: ev.version,
    P_GA: gaPool.id,
    P_VIP: vipPool.id,
    P_FS: fsPool.id,
    vPGA: ga.version,
    vPVIP: vip.version,
    vPFS: fs.version,
  };
}

export async function FX_EVENT_ONSALE_WITH_POOLS(): Promise<FX_EVENT_ONSALE_WITH_POOLS_Result> {
  const base = await FX_EVENT_DRAFT_WITH_POOLS();

  await putEventOnSale(base.W, base.E, base.vE);
  const ev = await getEvent(base.W, base.E);

  return {
    ...base,
    vE2: ev.version,
  };
}

export async function FX_EVENT_PAUSED_WITH_POOLS(): Promise<FX_EVENT_PAUSED_WITH_POOLS_Result> {
  const base = await FX_EVENT_ONSALE_WITH_POOLS();

  await pauseEvent(base.W, base.E, base.vE2);
  const ev = await getEvent(base.W, base.E);

  return {
    ...base,
    vE3: ev.version,
  };
}

export async function FX_EVENT_CLOSED_WITH_POOLS(): Promise<FX_EVENT_CLOSED_WITH_POOLS_Result> {
  const base = await FX_EVENT_ONSALE_WITH_POOLS();

  await closeEvent(base.W, base.E, base.vE2);
  const ev = await getEvent(base.W, base.E);

  return {
    ...base,
    vE4: ev.version,
  };
}

export async function FX_EVENT_CLOSED_WITH_ADMISSION(): Promise<FX_EVENT_CLOSED_WITH_ADMISSION_Result> {
  const base = await FX_EVENT_ONSALE_WITH_POOLS();

  const order = await createOrder(base.W, base.E, 'U1');
  const o1 = await getOrder(base.W, order.id);

  await setOrderLines(base.W, order.id, o1.version, [
    { pool_id: base.P_GA, quantity: 1 }
  ]);
  const o2 = await getOrder(base.W, order.id);

  await submitOrder(base.W, order.id, o2.version);
  const o3 = await getOrder(base.W, order.id);

  const payResult = await payOrder(base.W, order.id, o3.version);
  const admissionId = payResult.admission_ids[0];
  const admission = await getAdmission(base.W, admissionId);

  await closeEvent(base.W, base.E, base.vE2);
  const ev = await getEvent(base.W, base.E);

  return {
    ...base,
    OC: order.id,
    vOC: o1.version,
    vOC2: o2.version,
    vOC3: o3.version,
    AX: admissionId,
    vAX: admission.version,
    vE4b: ev.version,
  };
}

export async function FX_ORDER_DRAFT_U1(): Promise<FX_ORDER_DRAFT_U1_Result> {
  const base = await FX_EVENT_ONSALE_WITH_POOLS();

  const order = await createOrder(base.W, base.E, 'U1');
  const o = await getOrder(base.W, order.id);

  return {
    ...base,
    O: order.id,
    vO: o.version,
  };
}

export async function FX_ORDER_DRAFT_U1_GA2(): Promise<FX_ORDER_DRAFT_U1_GA2_Result> {
  const base = await FX_ORDER_DRAFT_U1();

  await setOrderLines(base.W, base.O, base.vO, [
    { pool_id: base.P_GA, quantity: 2 }
  ]);
  const o = await getOrder(base.W, base.O);

  return {
    ...base,
    vO2: o.version,
  };
}

export async function FX_ORDER_SUBMITTED_U1_GA2(): Promise<FX_ORDER_SUBMITTED_U1_GA2_Result> {
  const base = await FX_ORDER_DRAFT_U1_GA2();

  await submitOrder(base.W, base.O, base.vO2);
  const o = await getOrder(base.W, base.O);
  const pool = await getPool(base.W, base.E, base.P_GA);

  return {
    ...base,
    vO3: o.version,
    vPGA2: pool.version,
  };
}

export async function FX_ORDER_PAID_U1_GA2(): Promise<FX_ORDER_PAID_U1_GA2_Result> {
  const base = await FX_ORDER_SUBMITTED_U1_GA2();

  const payResult = await payOrder(base.W, base.O, base.vO3);
  const o = await getOrder(base.W, base.O);
  const pool = await getPool(base.W, base.E, base.P_GA);

  return {
    ...base,
    A1: payResult.admission_ids[0],
    A2: payResult.admission_ids[1],
    vO4: o.version,
    vPGA3: pool.version,
  };
}

export async function FX_ORDER_DRAFT_U1_VIP1(): Promise<FX_ORDER_DRAFT_U1_VIP1_Result> {
  const base = await FX_ORDER_DRAFT_U1();

  await setOrderLines(base.W, base.O, base.vO, [
    { pool_id: base.P_VIP, quantity: 1 }
  ]);
  const o = await getOrder(base.W, base.O);

  return {
    ...base,
    vO2: o.version,
  };
}

export async function FX_ORDER_SUBMITTED_U1_VIP1(): Promise<FX_ORDER_SUBMITTED_U1_VIP1_Result> {
  const base = await FX_ORDER_DRAFT_U1_VIP1();

  await submitOrder(base.W, base.O, base.vO2);
  const o = await getOrder(base.W, base.O);
  const pool = await getPool(base.W, base.E, base.P_VIP);

  return {
    ...base,
    vO3: o.version,
    vPVIP2: pool.version,
  };
}

export async function FX_ORDER_APPROVED_U1_VIP1(): Promise<FX_ORDER_APPROVED_U1_VIP1_Result> {
  const base = await FX_ORDER_SUBMITTED_U1_VIP1();

  await approveOrder(base.W, base.O, base.vO3, 'M1');
  const o = await getOrder(base.W, base.O);

  return {
    ...base,
    vO4: o.version,
  };
}

export async function FX_ORDER_PAID_U1_VIP1(): Promise<FX_ORDER_PAID_U1_VIP1_Result> {
  const base = await FX_ORDER_APPROVED_U1_VIP1();

  const payResult = await payOrder(base.W, base.O, base.vO4);
  const o = await getOrder(base.W, base.O);

  return {
    ...base,
    AV1: payResult.admission_ids[0],
    vO5: o.version,
  };
}

export async function FX_ORDER_PAID_U1_FS1(): Promise<FX_ORDER_PAID_U1_FS1_Result> {
  const base = await FX_EVENT_ONSALE_WITH_POOLS();

  const order = await createOrder(base.W, base.E, 'U1');
  const o1 = await getOrder(base.W, order.id);

  await setOrderLines(base.W, order.id, o1.version, [
    { pool_id: base.P_FS, quantity: 1 }
  ]);
  const o2 = await getOrder(base.W, order.id);

  await submitOrder(base.W, order.id, o2.version);
  const o3 = await getOrder(base.W, order.id);

  const payResult = await payOrder(base.W, order.id, o3.version);
  const o4 = await getOrder(base.W, order.id);

  return {
    ...base,
    O: order.id,
    vO: o1.version,
    vO2: o2.version,
    vO3: o3.version,
    AF1: payResult.admission_ids[0],
    vO4: o4.version,
  };
}

export async function FX_ORDER_PAID_U1_MIXED_GA1_VIP1(): Promise<FX_ORDER_PAID_U1_MIXED_GA1_VIP1_Result> {
  const base = await FX_EVENT_ONSALE_WITH_POOLS();

  const order = await createOrder(base.W, base.E, 'U1');
  const o1 = await getOrder(base.W, order.id);

  await setOrderLines(base.W, order.id, o1.version, [
    { pool_id: base.P_GA, quantity: 1 },
    { pool_id: base.P_VIP, quantity: 1 },
  ]);
  const o2 = await getOrder(base.W, order.id);

  await submitOrder(base.W, order.id, o2.version);
  const o3 = await getOrder(base.W, order.id);

  await approveOrder(base.W, order.id, o3.version, 'M1');
  const o4 = await getOrder(base.W, order.id);

  const payResult = await payOrder(base.W, order.id, o4.version);
  const o5 = await getOrder(base.W, order.id);

  return {
    ...base,
    O: order.id,
    vO: o1.version,
    vO2: o2.version,
    vO3: o3.version,
    vO4: o4.version,
    AM1: payResult.admission_ids[0],
    AM2: payResult.admission_ids[1],
    vO5: o5.version,
  };
}

export async function FX_EVENT_ONSALE_BOX(): Promise<FX_EVENT_ONSALE_BOX_Result> {
  const base = await FX_BASE_WS();

  const event = await createEvent(base.W, {
    title: 'BoxNight',
    starts_at_local: '2026-05-01T20:00',
    max_tickets_per_actor: 6,
  });
  const ev1 = await getEvent(base.W, event.id);

  const boxPool = await createPool(base.W, event.id, {
    label: 'BOX',
    kind: 'BOX',
    price_cents: 50000,
    currency: 'USD',
    capacity_total: 3,
    holdback_qty: 0,
    refund_policy: 'REFUNDABLE',
    transfer_policy: 'OPEN',
    pool_holdings_limit: 3,
  });

  await putEventOnSale(base.W, event.id, ev1.version);
  const ev2 = await getEvent(base.W, event.id);
  const pool = await getPool(base.W, event.id, boxPool.id);

  return {
    ...base,
    EB: event.id,
    vEB: ev1.version,
    P_BOX: boxPool.id,
    vEB2: ev2.version,
    vPBOX: pool.version,
  };
}

export async function FX_ORDER_SUBMITTED_U1_BOX2(): Promise<FX_ORDER_SUBMITTED_U1_BOX2_Result> {
  const base = await FX_EVENT_ONSALE_BOX();

  const order = await createOrder(base.W, base.EB, 'U1');
  const o1 = await getOrder(base.W, order.id);

  await setOrderLines(base.W, order.id, o1.version, [
    { pool_id: base.P_BOX, quantity: 2 }
  ]);
  const o2 = await getOrder(base.W, order.id);

  await submitOrder(base.W, order.id, o2.version);
  const o3 = await getOrder(base.W, order.id);

  return {
    ...base,
    O: order.id,
    vO: o1.version,
    vO2: o2.version,
    vO3: o3.version,
  };
}

export async function FX_LIMIT_EVENT_ONSALE(): Promise<FX_LIMIT_EVENT_ONSALE_Result> {
  const base = await FX_BASE_WS();

  const event = await createEvent(base.W, {
    title: 'LimitShow',
    starts_at_local: '2026-06-01T20:00',
    max_tickets_per_actor: 3,
  });
  const ev1 = await getEvent(base.W, event.id);

  const pool = await createPool(base.W, event.id, {
    label: 'LGA',
    kind: 'STANDARD',
    price_cents: 4000,
    currency: 'USD',
    capacity_total: 5,
    holdback_qty: 0,
    refund_policy: 'REFUNDABLE',
    transfer_policy: 'OPEN',
    pool_holdings_limit: 2,
  });

  await putEventOnSale(base.W, event.id, ev1.version);
  const ev2 = await getEvent(base.W, event.id);
  const p = await getPool(base.W, event.id, pool.id);

  return {
    ...base,
    EL: event.id,
    vEL: ev1.version,
    PLGA: pool.id,
    vEL2: ev2.version,
    vPLGA: p.version,
  };
}

export async function FX_LIMIT_ORDER_PAID_U1_GA2(): Promise<FX_LIMIT_ORDER_PAID_U1_GA2_Result> {
  const base = await FX_LIMIT_EVENT_ONSALE();

  const order = await createOrder(base.W, base.EL, 'U1');
  const o1 = await getOrder(base.W, order.id);

  await setOrderLines(base.W, order.id, o1.version, [
    { pool_id: base.PLGA, quantity: 2 }
  ]);
  const o2 = await getOrder(base.W, order.id);

  await submitOrder(base.W, order.id, o2.version);
  const o3 = await getOrder(base.W, order.id);

  const payResult = await payOrder(base.W, order.id, o3.version);
  const o4 = await getOrder(base.W, order.id);

  return {
    ...base,
    O1: order.id,
    vO1: o1.version,
    vO12: o2.version,
    vO13: o3.version,
    L1: payResult.admission_ids[0],
    L2: payResult.admission_ids[1],
    vO14: o4.version,
  };
}

export async function FX_LIMIT_ORDER_PAID_U2_GA2(): Promise<FX_LIMIT_ORDER_PAID_U2_GA2_Result> {
  const base = await FX_LIMIT_EVENT_ONSALE();

  const order = await createOrder(base.W, base.EL, 'U2');
  const o1 = await getOrder(base.W, order.id);

  await setOrderLines(base.W, order.id, o1.version, [
    { pool_id: base.PLGA, quantity: 2 }
  ]);
  const o2 = await getOrder(base.W, order.id);

  await submitOrder(base.W, order.id, o2.version);
  const o3 = await getOrder(base.W, order.id);

  const payResult = await payOrder(base.W, order.id, o3.version);
  const o4 = await getOrder(base.W, order.id);

  return {
    ...base,
    O2: order.id,
    vO2: o1.version,
    vO22: o2.version,
    vO23: o3.version,
    L3: payResult.admission_ids[0],
    L4: payResult.admission_ids[1],
    vO24: o4.version,
  };
}

export async function FX_OVERALLOCATED_POOL(): Promise<FX_OVERALLOCATED_POOL_Result> {
  const base = await FX_BASE_WS();

  const event = await createEvent(base.W, {
    title: 'TightCap',
    starts_at_local: '2026-07-01T20:00',
    max_tickets_per_actor: 6,
  });
  const ev1 = await getEvent(base.W, event.id);

  const pool = await createPool(base.W, event.id, {
    label: 'TC',
    kind: 'STANDARD',
    price_cents: 3000,
    currency: 'USD',
    capacity_total: 5,
    holdback_qty: 0,
    refund_policy: 'REFUNDABLE',
    transfer_policy: 'OPEN',
    pool_holdings_limit: 6,
  });

  await putEventOnSale(base.W, event.id, ev1.version);
  const ev2 = await getEvent(base.W, event.id);

  const order = await createOrder(base.W, event.id, 'U1');
  const o1 = await getOrder(base.W, order.id);

  await setOrderLines(base.W, order.id, o1.version, [
    { pool_id: pool.id, quantity: 4 }
  ]);
  const o2 = await getOrder(base.W, order.id);

  await submitOrder(base.W, order.id, o2.version);
  const p2 = await getPool(base.W, event.id, pool.id);

  await adjustPool(base.W, event.id, pool.id, p2.version, {
    capacity_delta: -3,
    holdback_delta: 0,
    note: 'shrink',
  });
  const p3 = await getPool(base.W, event.id, pool.id);
  const ws = await getWorkspace(base.W);

  return {
    ...base,
    EO: event.id,
    vEO: ev1.version,
    PTC: pool.id,
    vEO2: ev2.version,
    O: order.id,
    vO: o1.version,
    vO2: o2.version,
    vPTC2: p2.version,
    vPTC3: p3.version,
    vW2: ws.version,
  };
}

export async function FX_CANCELLED_EVENT_WITH_PAID(): Promise<FX_CANCELLED_EVENT_WITH_PAID_Result> {
  const base = await FX_ORDER_PAID_U1_GA2();

  const ev1 = await getEvent(base.W, base.E);
  await cancelEvent(base.W, base.E, ev1.version);
  const ev2 = await getEvent(base.W, base.E);
  const ws = await getWorkspace(base.W);

  return {
    ...base,
    vE5: ev1.version,
    vE6: ev2.version,
    vW2: ws.version,
  };
}

export async function FX_CANCELLED_EVENT_REMEDIED(): Promise<FX_CANCELLED_EVENT_REMEDIED_Result> {
  const base = await FX_CANCELLED_EVENT_WITH_PAID();

  const o1 = await getOrder(base.W, base.O);
  await refundOrder(base.W, base.O, o1.version, 'EVENT_CANCELLED', 'M1');
  const o2 = await getOrder(base.W, base.O);
  const ws = await getWorkspace(base.W);

  return {
    ...base,
    vO5: o1.version,
    vO6: o2.version,
    vW3: ws.version,
  };
}

export async function FX_WS_TWO_EVENTS_HALT_WITH_SCANABLE(): Promise<FX_WS_TWO_EVENTS_HALT_WITH_SCANABLE_Result> {
  const base = await FX_BASE_WS();

  const event1 = await createEvent(base.W, {
    title: 'E1',
    starts_at_local: '2026-08-01T20:00',
    max_tickets_per_actor: 6,
  });
  const ev1 = await getEvent(base.W, event1.id);

  const pool1 = await createPool(base.W, event1.id, {
    label: 'E1GA',
    kind: 'STANDARD',
    price_cents: 2000,
    currency: 'USD',
    capacity_total: 3,
    holdback_qty: 0,
    refund_policy: 'REFUNDABLE',
    transfer_policy: 'OPEN',
    pool_holdings_limit: 6,
  });

  const event2 = await createEvent(base.W, {
    title: 'E2',
    starts_at_local: '2026-08-02T20:00',
    max_tickets_per_actor: 6,
  });
  const ev2 = await getEvent(base.W, event2.id);

  const pool2 = await createPool(base.W, event2.id, {
    label: 'E2GA',
    kind: 'STANDARD',
    price_cents: 2000,
    currency: 'USD',
    capacity_total: 3,
    holdback_qty: 0,
    refund_policy: 'REFUNDABLE',
    transfer_policy: 'OPEN',
    pool_holdings_limit: 6,
  });

  await putEventOnSale(base.W, event1.id, ev1.version);
  await putEventOnSale(base.W, event2.id, ev2.version);

  const order2 = await createOrder(base.W, event2.id, 'U1');
  const o2_1 = await getOrder(base.W, order2.id);
  await setOrderLines(base.W, order2.id, o2_1.version, [{ pool_id: pool2.id, quantity: 1 }]);
  const o2_2 = await getOrder(base.W, order2.id);
  await submitOrder(base.W, order2.id, o2_2.version);
  const o2_3 = await getOrder(base.W, order2.id);
  const payResult2 = await payOrder(base.W, order2.id, o2_3.version);

  const order1 = await createOrder(base.W, event1.id, 'U1');
  const o1_1 = await getOrder(base.W, order1.id);
  await setOrderLines(base.W, order1.id, o1_1.version, [{ pool_id: pool1.id, quantity: 1 }]);
  const o1_2 = await getOrder(base.W, order1.id);
  await submitOrder(base.W, order1.id, o1_2.version);
  const o1_3 = await getOrder(base.W, order1.id);
  const payResult1 = await payOrder(base.W, order1.id, o1_3.version);

  const ev1b = await getEvent(base.W, event1.id);
  await cancelEvent(base.W, event1.id, ev1b.version);
  const ws = await getWorkspace(base.W);

  const a2 = await getAdmission(base.W, payResult2.admission_ids[0]);

  return {
    ...base,
    E1: event1.id,
    vE1: ev1.version,
    P1: pool1.id,
    E2: event2.id,
    vE2: ev2.version,
    P2: pool2.id,
    O2: order2.id,
    vO2: o2_1.version,
    vO22: o2_2.version,
    vO23: o2_3.version,
    A2E2: payResult2.admission_ids[0],
    O1: order1.id,
    vO1: o1_1.version,
    vO12: o1_2.version,
    vO13: o1_3.version,
    A1E1: payResult1.admission_ids[0],
    vE1b: ev1b.version,
    vW2: ws.version,
    vA2: a2.version,
  };
}

export async function FX_WS_HALT_WITH_EXISTING_DRAFT_ORDER(): Promise<FX_WS_HALT_WITH_EXISTING_DRAFT_ORDER_Result> {
  const base = await FX_BASE_WS();

  const event1 = await createEvent(base.W, {
    title: 'HX1',
    starts_at_local: '2026-10-01T20:00',
    max_tickets_per_actor: 6,
  });
  const ev1 = await getEvent(base.W, event1.id);

  const pool1 = await createPool(base.W, event1.id, {
    label: 'HX1GA',
    kind: 'STANDARD',
    price_cents: 2000,
    currency: 'USD',
    capacity_total: 3,
    holdback_qty: 0,
    refund_policy: 'REFUNDABLE',
    transfer_policy: 'OPEN',
    pool_holdings_limit: 6,
  });

  const event2 = await createEvent(base.W, {
    title: 'HX2',
    starts_at_local: '2026-10-02T20:00',
    max_tickets_per_actor: 6,
  });
  const ev2 = await getEvent(base.W, event2.id);

  const pool2 = await createPool(base.W, event2.id, {
    label: 'HX2GA',
    kind: 'STANDARD',
    price_cents: 2000,
    currency: 'USD',
    capacity_total: 3,
    holdback_qty: 0,
    refund_policy: 'REFUNDABLE',
    transfer_policy: 'OPEN',
    pool_holdings_limit: 6,
  });

  await putEventOnSale(base.W, event1.id, ev1.version);
  await putEventOnSale(base.W, event2.id, ev2.version);

  const orderH = await createOrder(base.W, event2.id, 'U2');
  const oH = await getOrder(base.W, orderH.id);
  await setOrderLines(base.W, orderH.id, oH.version, [{ pool_id: pool2.id, quantity: 1 }]);
  const oH2 = await getOrder(base.W, orderH.id);

  const orderHP = await createOrder(base.W, event1.id, 'U1');
  const oHP1 = await getOrder(base.W, orderHP.id);
  await setOrderLines(base.W, orderHP.id, oHP1.version, [{ pool_id: pool1.id, quantity: 1 }]);
  const oHP2 = await getOrder(base.W, orderHP.id);
  await submitOrder(base.W, orderHP.id, oHP2.version);
  const oHP3 = await getOrder(base.W, orderHP.id);
  const payResultHP = await payOrder(base.W, orderHP.id, oHP3.version);

  const ev1b = await getEvent(base.W, event1.id);
  await cancelEvent(base.W, event1.id, ev1b.version);
  const ws = await getWorkspace(base.W);

  return {
    ...base,
    EH1: event1.id,
    vEH1: ev1.version,
    PH1: pool1.id,
    EH2: event2.id,
    vEH2: ev2.version,
    PH2: pool2.id,
    OH: orderH.id,
    vOH: oH2.version,
    OHP: orderHP.id,
    vOHP: oHP1.version,
    vOHP2: oHP2.version,
    vOHP3: oHP3.version,
    AHP1: payResultHP.admission_ids[0],
    vEH1b: ev1b.version,
    vWH: ws.version,
  };
}
