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
  refundOrder,
  Admission,
} from '../../../test-helpers/resources';
import {
  FX_ORDER_PAID_U1_GA2,
  FX_CANCELLED_EVENT_WITH_PAID,
  FX_WS_TWO_EVENTS_HALT_WITH_SCANABLE,
  FX_EVENT_CLOSED_WITH_ADMISSION,
} from '../../../test-helpers/fixtures';
import { ERROR_CODES } from '../../../test-helpers/constants';

describe('Feature 9: Gate Scanning Tests', () => {

  test('SCAN_001: Scan by GATE role succeeds, marks SCANNED and records scanned_by_actor_id', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();
    const admission = await getAdmission(fx.W, fx.A1);

    expect(admission.state).toBe('ACTIVE');

    const res = await postAs(
      `/workspaces/${fx.W}/admissions/${fx.A1}/scan`,
      {},
      { role: 'GATE', actorId: 'G1', ifMatch: admission.version }
    );

    expectSuccess(res);
    const admissionAfter = await getAdmission(fx.W, fx.A1);
    expect(admissionAfter.state).toBe('SCANNED');
    expect(admissionAfter.scanned_by_actor_id).toBe('G1');
  });

  test('SCAN_002: Scanning already scanned admission returns ERR_ADMISSION_ALREADY_SCANNED', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();
    const admission1 = await getAdmission(fx.W, fx.A1);

    const scanRes = await postAs(
      `/workspaces/${fx.W}/admissions/${fx.A1}/scan`,
      {},
      { role: 'GATE', actorId: 'G1', ifMatch: admission1.version }
    );
    expectSuccess(scanRes);

    const admission2 = await getAdmission(fx.W, fx.A1);
    expect(admission2.state).toBe('SCANNED');

    const res = await postAs(
      `/workspaces/${fx.W}/admissions/${fx.A1}/scan`,
      {},
      { role: 'GATE', actorId: 'G1', ifMatch: admission2.version }
    );

    expectErrorCode(res, ERROR_CODES.ADMISSION_ALREADY_SCANNED);
    const admissionAfter = await getAdmission(fx.W, fx.A1);
    expect(admissionAfter.state).toBe('SCANNED');
  });

  test('SCAN_003: Scanning voided admission returns ERR_ADMISSION_VOIDED', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();

    const order = await getOrder(fx.W, fx.O);
    await refundOrder(fx.W, fx.O, order.version, 'FRAUD', 'M1');

    const admission = await getAdmission(fx.W, fx.A1);
    expect(admission.state).toBe('VOIDED');

    const res = await postAs(
      `/workspaces/${fx.W}/admissions/${fx.A1}/scan`,
      {},
      { role: 'GATE', actorId: 'G1', ifMatch: admission.version }
    );

    expectErrorCode(res, ERROR_CODES.ADMISSION_VOIDED);
    const admissionAfter = await getAdmission(fx.W, fx.A1);
    expect(admissionAfter.state).toBe('VOIDED');
  });

  test('SCAN_005: Scanning admission for cancelled event returns ERR_SCAN_NOT_ALLOWED', async () => {

    const fx = await FX_CANCELLED_EVENT_WITH_PAID();

    const ev = await getEvent(fx.W, fx.E);
    expect(ev.status).toBe('CANCELLED');

    const admission = await getAdmission(fx.W, fx.A1);

    const res = await postAs(
      `/workspaces/${fx.W}/admissions/${fx.A1}/scan`,
      {},
      { role: 'GATE', actorId: 'G1', ifMatch: admission.version }
    );

    expectErrorCode(res, ERROR_CODES.SCAN_NOT_ALLOWED);
    const admissionAfter = await getAdmission(fx.W, fx.A1);

    expect(admissionAfter.state).not.toBe('SCANNED');
  });

  test('SCAN_006: Scan by SELLER role returns ERR_ROLE_FORBIDDEN', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();
    const admission = await getAdmission(fx.W, fx.A1);

    expect(admission.state).toBe('ACTIVE');

    const res = await postAs(
      `/workspaces/${fx.W}/admissions/${fx.A1}/scan`,
      {},
      { role: 'SELLER', actorId: 'U1', ifMatch: admission.version }
    );

    expectErrorCode(res, ERROR_CODES.ROLE_FORBIDDEN);
    const admissionAfter = await getAdmission(fx.W, fx.A1);
    expect(admissionAfter.state).toBe('ACTIVE');
  });

  test('SCAN_007: Scan without If-Match returns ERR_MISSING_IF_MATCH', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();

    const admissionBefore = await getAdmission(fx.W, fx.A1);
    expect(admissionBefore.state).toBe('ACTIVE');

    const res = await postAs(
      `/workspaces/${fx.W}/admissions/${fx.A1}/scan`,
      {},
      { role: 'GATE', actorId: 'G1', skipIfMatch: true }
    );

    expectErrorCode(res, ERROR_CODES.MISSING_IF_MATCH);
    const admissionAfter = await getAdmission(fx.W, fx.A1);
    expect(admissionAfter.state).toBe('ACTIVE');
  });

  test('SCAN_008: Scan with stale If-Match returns ERR_VERSION_CONFLICT', async () => {

    const fx = await FX_ORDER_PAID_U1_GA2();

    const admissionBefore = await getAdmission(fx.W, fx.A1);
    expect(admissionBefore.state).toBe('ACTIVE');

    const res = await postAs(
      `/workspaces/${fx.W}/admissions/${fx.A1}/scan`,
      {},
      { role: 'GATE', actorId: 'G1', ifMatch: 'stale' }
    );

    expectErrorCode(res, ERROR_CODES.VERSION_CONFLICT);
    const admissionAfter = await getAdmission(fx.W, fx.A1);
    expect(admissionAfter.state).toBe('ACTIVE');
  });

  test('SCAN_009: Scan works during HALT posture for non-cancelled event', async () => {

    const fx = await FX_WS_TWO_EVENTS_HALT_WITH_SCANABLE();

    const ws = await getWorkspace(fx.W);
    expect(ws.posture).toBe('HALT');

    const ev2 = await getEvent(fx.W, fx.E2);
    expect(ev2.status).toBe('ONSALE');

    const res = await postAs(
      `/workspaces/${fx.W}/admissions/${fx.A2E2}/scan`,
      {},
      { role: 'GATE', actorId: 'G1', ifMatch: fx.vA2 }
    );

    expectSuccess(res);
    const admissionAfter = await getAdmission(fx.W, fx.A2E2);
    expect(admissionAfter.state).toBe('SCANNED');
    expect(admissionAfter.scanned_by_actor_id).toBe('G1');

    const wsAfter = await getWorkspace(fx.W);
    expect(wsAfter.posture).toBe('HALT');
  });

  test('SCAN_010: Scan succeeds on CLOSED event', async () => {

    const fx = await FX_EVENT_CLOSED_WITH_ADMISSION();

    const ev = await getEvent(fx.W, fx.E);
    expect(ev.status).toBe('CLOSED');

    const admission = await getAdmission(fx.W, fx.AX);
    expect(admission.state).toBe('ACTIVE');

    const res = await postAs(
      `/workspaces/${fx.W}/admissions/${fx.AX}/scan`,
      {},
      { role: 'GATE', actorId: 'G1', ifMatch: admission.version }
    );

    expectSuccess(res);
    const admissionAfter = await getAdmission(fx.W, fx.AX);
    expect(admissionAfter.state).toBe('SCANNED');
    expect(admissionAfter.scanned_by_actor_id).toBe('G1');
  });
});
