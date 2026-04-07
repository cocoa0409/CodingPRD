import {
  postAs,
  getAs,
} from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
  extractData,
} from '../../../test-helpers/assertions';
import {
  getWorkspace,
  getOrder,
  getAdmission,
  getEvent,
  createOrder,
  setOrderLines,
  submitOrder,
  payOrder,
  refundOrder,
  closeEvent,
  pauseEvent,
  transferAdmission,
  Order,
} from '../../../test-helpers/resources';
import {
  FX_ORDER_PAID_U1_GA2,
  FX_ORDER_PAID_U1_VIP1,
  FX_ORDER_PAID_U1_FS1,
  FX_EVENT_CLOSED_WITH_ADMISSION,
  FX_CANCELLED_EVENT_WITH_PAID,
  FX_LIMIT_EVENT_ONSALE,
} from '../../../test-helpers/fixtures';
import { ERROR_CODES } from '../../../test-helpers/constants';

describe('Feature 8: Transfers and Ticket State Tests', () => {

  test('XFER_001: Transfer by holder succeeds, increments transfer_count', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();
    const admission = await getAdmission(fx.W, fx.A1);

    expect(admission.holder_actor_id).toBe('U1');
    expect(admission.transfer_count).toBe(0);

    const res = await postAs(
      `/workspaces/${fx.W}/admissions/${fx.A1}/transfer`,
      { to_actor_id: 'U2' },
      { role: 'SELLER', actorId: 'U1', ifMatch: admission.version }
    );

    expectSuccess(res);
    const admissionAfter = await getAdmission(fx.W, fx.A1);
    expect(admissionAfter.holder_actor_id).toBe('U2');
    expect(admissionAfter.transfer_count).toBe(1);
    expect(admissionAfter.state).toBe('ACTIVE');
  });

  test('XFER_002: Transfer by non-holder returns ERR_NOT_HOLDER', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();
    const admission = await getAdmission(fx.W, fx.A1);

    expect(admission.holder_actor_id).toBe('U1');

    const res = await postAs(
      `/workspaces/${fx.W}/admissions/${fx.A1}/transfer`,
      { to_actor_id: 'U2' },
      { role: 'SELLER', actorId: 'U9', ifMatch: admission.version }
    );

    expectErrorCode(res, ERROR_CODES.NOT_HOLDER);
    const admissionAfter = await getAdmission(fx.W, fx.A1);
    expect(admissionAfter.holder_actor_id).toBe('U1');
  });

  test('XFER_003: Transfer by MANAGER role is permitted and changes holder', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();
    const admission1 = await getAdmission(fx.W, fx.A1);

    await transferAdmission(fx.W, fx.A1, admission1.version, 'M1', 'U1');
    const admission2 = await getAdmission(fx.W, fx.A1);
    expect(admission2.holder_actor_id).toBe('M1');
    expect(admission2.transfer_count).toBe(1);

    const res = await postAs(
      `/workspaces/${fx.W}/admissions/${fx.A1}/transfer`,
      { to_actor_id: 'U2' },
      { role: 'MANAGER', actorId: 'M1', ifMatch: admission2.version }
    );

    expectSuccess(res);
    const admissionAfter = await getAdmission(fx.W, fx.A1);
    expect(admissionAfter.holder_actor_id).toBe('U2');
    expect(admissionAfter.transfer_count).toBe(2);
  });

  test('XFER_004: Transfer on NONE policy pool returns ERR_POOL_TRANSFER_BLOCKED', async () => {

    const fx = await FX_ORDER_PAID_U1_FS1();
    const admission = await getAdmission(fx.W, fx.AF1);

    expect(admission.transfer_count).toBe(0);

    const res = await postAs(
      `/workspaces/${fx.W}/admissions/${fx.AF1}/transfer`,
      { to_actor_id: 'U2' },
      { role: 'SELLER', actorId: 'U1', ifMatch: admission.version }
    );

    expectErrorCode(res, ERROR_CODES.POOL_TRANSFER_BLOCKED);
    const admissionAfter = await getAdmission(fx.W, fx.AF1);
    expect(admissionAfter.transfer_count).toBe(0);
  });

  test('XFER_005: Second transfer on ONCE policy pool returns ERR_POOL_TRANSFER_BLOCKED', async () => {

    const fx = await FX_ORDER_PAID_U1_VIP1();
    const admission1 = await getAdmission(fx.W, fx.AV1);

    await transferAdmission(fx.W, fx.AV1, admission1.version, 'U2', 'U1');
    const admission2 = await getAdmission(fx.W, fx.AV1);
    expect(admission2.holder_actor_id).toBe('U2');
    expect(admission2.transfer_count).toBe(1);

    const res = await postAs(
      `/workspaces/${fx.W}/admissions/${fx.AV1}/transfer`,
      { to_actor_id: 'U3' },
      { role: 'SELLER', actorId: 'U2', ifMatch: admission2.version }
    );

    expectErrorCode(res, ERROR_CODES.POOL_TRANSFER_BLOCKED);
    const admissionAfter = await getAdmission(fx.W, fx.AV1);
    expect(admissionAfter.holder_actor_id).toBe('U2');
    expect(admissionAfter.transfer_count).toBe(1);
  });

  test('XFER_006: Second transfer in REVIEW posture returns ERR_POOL_TRANSFER_BLOCKED', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();
    const admission1 = await getAdmission(fx.W, fx.A1);

    await transferAdmission(fx.W, fx.A1, admission1.version, 'U2', 'U1');
    const admission2 = await getAdmission(fx.W, fx.A1);
    expect(admission2.holder_actor_id).toBe('U2');
    expect(admission2.transfer_count).toBe(1);

    const ev = await getEvent(fx.W, fx.E);
    await pauseEvent(fx.W, fx.E, ev.version);

    const ws = await getWorkspace(fx.W);
    expect(ws.posture).toBe('REVIEW');

    const admission3 = await getAdmission(fx.W, fx.A1);

    const res = await postAs(
      `/workspaces/${fx.W}/admissions/${fx.A1}/transfer`,
      { to_actor_id: 'U3' },
      { role: 'SELLER', actorId: 'U2', ifMatch: admission3.version }
    );

    expectErrorCode(res, ERROR_CODES.POOL_TRANSFER_BLOCKED);
    const admissionAfter = await getAdmission(fx.W, fx.A1);
    expect(admissionAfter.transfer_count).toBe(1);
    expect(admissionAfter.holder_actor_id).toBe('U2');
  });

  test('XFER_007: Transfer on CLOSED event returns ERR_POOL_TRANSFER_BLOCKED', async () => {

    const fx = await FX_EVENT_CLOSED_WITH_ADMISSION();

    const ev = await getEvent(fx.W, fx.E);
    expect(ev.status).toBe('CLOSED');

    const admission = await getAdmission(fx.W, fx.AX);

    const res = await postAs(
      `/workspaces/${fx.W}/admissions/${fx.AX}/transfer`,
      { to_actor_id: 'U2' },
      { role: 'SELLER', actorId: 'U1', ifMatch: admission.version }
    );

    expectErrorCode(res, ERROR_CODES.POOL_TRANSFER_BLOCKED);
    const admissionAfter = await getAdmission(fx.W, fx.AX);
    expect(admissionAfter.holder_actor_id).toBe('U1');
  });

  test('XFER_008: Transfer in HALT posture by SELLER returns ERR_POSTURE_BLOCKED', async () => {

    const fx = await FX_CANCELLED_EVENT_WITH_PAID();

    const ws = await getWorkspace(fx.W);
    expect(ws.posture).toBe('HALT');

    const admission = await getAdmission(fx.W, fx.A1);

    const res = await postAs(
      `/workspaces/${fx.W}/admissions/${fx.A1}/transfer`,
      { to_actor_id: 'U2' },
      { role: 'SELLER', actorId: 'U1', ifMatch: admission.version }
    );

    expectErrorCode(res, ERROR_CODES.POSTURE_BLOCKED);
    const admissionAfter = await getAdmission(fx.W, fx.A1);
    expect(admissionAfter.holder_actor_id).toBe('U1');
  });

  test('XFER_009: Transfer in HALT posture by MANAGER returns ERR_POSTURE_BLOCKED', async () => {

    const fx = await FX_CANCELLED_EVENT_WITH_PAID();

    const ws = await getWorkspace(fx.W);
    expect(ws.posture).toBe('HALT');

    const admission = await getAdmission(fx.W, fx.A1);

    const res = await postAs(
      `/workspaces/${fx.W}/admissions/${fx.A1}/transfer`,
      { to_actor_id: 'U2' },
      { role: 'MANAGER', actorId: 'M1', ifMatch: admission.version }
    );

    expectErrorCode(res, ERROR_CODES.POSTURE_BLOCKED);
    const admissionAfter = await getAdmission(fx.W, fx.A1);
    expect(admissionAfter.holder_actor_id).toBe('U1');
  });

  test('XFER_010: Transfer of VOIDED admission returns ERR_ADMISSION_VOIDED', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();

    const order = await getOrder(fx.W, fx.O);
    await refundOrder(fx.W, fx.O, order.version, 'FRAUD', 'M1');

    const admission = await getAdmission(fx.W, fx.A1);
    expect(admission.state).toBe('VOIDED');

    const res = await postAs(
      `/workspaces/${fx.W}/admissions/${fx.A1}/transfer`,
      { to_actor_id: 'U2' },
      { role: 'SELLER', actorId: 'U1', ifMatch: admission.version }
    );

    expectErrorCode(res, ERROR_CODES.ADMISSION_VOIDED);
    const admissionAfter = await getAdmission(fx.W, fx.A1);
    expect(admissionAfter.holder_actor_id).toBe('U1');
    expect(admissionAfter.transfer_count).toBe(0);
  });

  test('XFER_011: Transfer does not change order status', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();

    const orderBefore = await getOrder(fx.W, fx.O);
    expect(orderBefore.status).toBe('PAID');

    const admission = await getAdmission(fx.W, fx.A1);
    await transferAdmission(fx.W, fx.A1, admission.version, 'U2', 'U1');

    const res = await getAs(`/workspaces/${fx.W}/orders/${fx.O}`);

    expectSuccess(res);
    const orderAfter = extractData<Order>(res);
    expect(orderAfter.status).toBe('PAID');
  });

  test('XFER_012: Transfer that exceeds holdings limit returns ERR_HOLDINGS_LIMIT_EXCEEDED', async () => {

    const fx = await FX_LIMIT_EVENT_ONSALE();

    const orderU1 = await createOrder(fx.W, fx.EL, 'U1');
    const oU1_1 = await getOrder(fx.W, orderU1.id);
    await setOrderLines(fx.W, orderU1.id, oU1_1.version, [{ pool_id: fx.PLGA, quantity: 2 }]);
    const oU1_2 = await getOrder(fx.W, orderU1.id);
    await submitOrder(fx.W, orderU1.id, oU1_2.version);
    const oU1_3 = await getOrder(fx.W, orderU1.id);
    const payResultU1 = await payOrder(fx.W, orderU1.id, oU1_3.version);

    const u1Admission1 = await getAdmission(fx.W, payResultU1.admission_ids[0]);
    const u1Admission2 = await getAdmission(fx.W, payResultU1.admission_ids[1]);
    expect(u1Admission1.holder_actor_id).toBe('U1');
    expect(u1Admission1.state).toBe('ACTIVE');
    expect(u1Admission2.holder_actor_id).toBe('U1');
    expect(u1Admission2.state).toBe('ACTIVE');

    const orderU2 = await createOrder(fx.W, fx.EL, 'U2');
    const oU2_1 = await getOrder(fx.W, orderU2.id);
    await setOrderLines(fx.W, orderU2.id, oU2_1.version, [{ pool_id: fx.PLGA, quantity: 1 }]);
    const oU2_2 = await getOrder(fx.W, orderU2.id);
    await submitOrder(fx.W, orderU2.id, oU2_2.version);
    const oU2_3 = await getOrder(fx.W, orderU2.id);
    const payResultU2 = await payOrder(fx.W, orderU2.id, oU2_3.version);
    const admissionU2 = payResultU2.admission_ids[0];

    const admission = await getAdmission(fx.W, admissionU2);
    expect(admission.holder_actor_id).toBe('U2');
    expect(admission.state).toBe('ACTIVE');
    expect(admission.transfer_count).toBe(0);

    const res = await postAs(
      `/workspaces/${fx.W}/admissions/${admissionU2}/transfer`,
      { to_actor_id: 'U1' },
      { role: 'SELLER', actorId: 'U2', ifMatch: admission.version }
    );

    expectErrorCode(res, ERROR_CODES.HOLDINGS_LIMIT_EXCEEDED);
    const admissionAfter = await getAdmission(fx.W, admissionU2);
    expect(admissionAfter.holder_actor_id).toBe('U2');
    expect(admissionAfter.transfer_count).toBe(0);
  });

  test('XFER_013: Transfer by AUDITOR role returns ERR_ROLE_FORBIDDEN', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();
    const admission = await getAdmission(fx.W, fx.A1);

    const res = await postAs(
      `/workspaces/${fx.W}/admissions/${fx.A1}/transfer`,
      { to_actor_id: 'U2' },
      { role: 'AUDITOR', actorId: 'AUD1', ifMatch: admission.version }
    );

    expectErrorCode(res, ERROR_CODES.ROLE_FORBIDDEN);
    const admissionAfter = await getAdmission(fx.W, fx.A1);
    expect(admissionAfter.holder_actor_id).toBe('U1');
    expect(admissionAfter.transfer_count).toBe(0);
  });

  test('XFER_014: Transfer without If-Match returns ERR_MISSING_IF_MATCH', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();

    const res = await postAs(
      `/workspaces/${fx.W}/admissions/${fx.A1}/transfer`,
      { to_actor_id: 'U2' },
      { role: 'SELLER', actorId: 'U1', skipIfMatch: true }
    );

    expectErrorCode(res, ERROR_CODES.MISSING_IF_MATCH);
    const admissionAfter = await getAdmission(fx.W, fx.A1);
    expect(admissionAfter.holder_actor_id).toBe('U1');
    expect(admissionAfter.transfer_count).toBe(0);
  });

  test('XFER_015: Transfer with stale If-Match returns ERR_VERSION_CONFLICT', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();

    const res = await postAs(
      `/workspaces/${fx.W}/admissions/${fx.A1}/transfer`,
      { to_actor_id: 'U2' },
      { role: 'SELLER', actorId: 'U1', ifMatch: 'stale' }
    );

    expectErrorCode(res, ERROR_CODES.VERSION_CONFLICT);
    const admissionAfter = await getAdmission(fx.W, fx.A1);
    expect(admissionAfter.holder_actor_id).toBe('U1');
    expect(admissionAfter.transfer_count).toBe(0);
  });

  test('XFER_016: Transfer after event is closed returns ERR_POOL_TRANSFER_BLOCKED', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();

    const admission1 = await getAdmission(fx.W, fx.A1);

    const ev = await getEvent(fx.W, fx.E);
    await closeEvent(fx.W, fx.E, ev.version);

    const evClosed = await getEvent(fx.W, fx.E);
    expect(evClosed.status).toBe('CLOSED');

    const admission2 = await getAdmission(fx.W, fx.A1);

    const res = await postAs(
      `/workspaces/${fx.W}/admissions/${fx.A1}/transfer`,
      { to_actor_id: 'U2' },
      { role: 'SELLER', actorId: 'U1', ifMatch: admission2.version }
    );

    expectErrorCode(res, ERROR_CODES.POOL_TRANSFER_BLOCKED);
    const admissionAfter = await getAdmission(fx.W, fx.A1);
    expect(admissionAfter.holder_actor_id).toBe('U1');
    expect(admissionAfter.transfer_count).toBe(0);
  });
});
