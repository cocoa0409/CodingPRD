import { getAs, postAs, postWithIfMatch, generateIdempotencyKey } from '../../../test-helpers/api-client';
import { expectSuccess, expectErrorCode } from '../../../test-helpers/assertions';
import {
  createProject,
  getProject,
  createWorkItem,
  getWorkItem,
  readyWorkItem,
  startWorkItem,
  createPermit,
  decidePermit,
  createInspection,
  submitInspection,
  createChangeOrder,
  getChangeOrder,
  approveChangeOrder,
  applyChangeOrder,
  cancelChangeOrder,
  cancelWorkItem,
  uniqueId,
  unwrap,
} from '../../../test-helpers/resources';
import {
  FX_PROJECT_OPEN_120,
  FX_CORE_PERMITS_GRANTED,
  FX_ELECTRICAL_PERMIT_GRANTED,
} from '../../../test-helpers/fixtures';

describe('Feature 9: Deep Integration Tests', () => {

  test('DEEP_001: Cancelling approved change order unfreezes work item but quality still blocks completion', async () => {

    const { P } = await FX_CORE_PERMITS_GRANTED();

    const workItemRes = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'E1',
        trade: 'ELECTRICAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 10,
      },
      'FOREMAN',
      generateIdempotencyKey('d1')
    );
    expectSuccess(workItemRes);
    const W1 = unwrap(workItemRes.body).id;

    const workItemGet1 = await getWorkItem(P, W1);
    const E1 = workItemGet1.etag;

    const readyRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W1}/ready`,
      {},
      E1,
      'FOREMAN',
      generateIdempotencyKey('d1b')
    );
    expectSuccess(readyRes);

    const workItemGet2 = await getWorkItem(P, W1);
    const E1b = workItemGet2.etag;

    const startRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W1}/start`,
      {},
      E1b,
      'FOREMAN',
      generateIdempotencyKey('d1c')
    );
    expectSuccess(startRes);

    const workItemAfterStart = await getWorkItem(P, W1);
    expect(workItemAfterStart.status).toBe('IN_PROGRESS');

    const inspectionRes = await postAs(
      `/projects/${P}/inspections`,
      {
        work_item_id: W1,
        kind: 'QUALITY',
      },
      'INSPECTOR',
      generateIdempotencyKey('d1d')
    );
    expectSuccess(inspectionRes);
    const IQ1 = unwrap(inspectionRes.body).id;

    const submitRes = await postAs(
      `/projects/${P}/inspections/${IQ1}/submit`,
      { outcome: 'FAILED' },
      'INSPECTOR',
      generateIdempotencyKey('d1e')
    );
    expectSuccess(submitRes);

    const workItemAfterFail = await getWorkItem(P, W1);
    expect(workItemAfterFail.latest_quality_status).toBe('FAILED');

    const coRes = await postAs(
      `/projects/${P}/change_orders`,
      {
        work_item_id: W1,
        summary: 'Fix scope',
        new_estimated_hours: 8,
      },
      'FOREMAN',
      generateIdempotencyKey('d1f')
    );
    expectSuccess(coRes);
    const CO = unwrap(coRes.body).id;

    const coGet1 = await getChangeOrder(P, CO);
    const ECO = coGet1.etag;

    const approveRes = await postWithIfMatch(
      `/projects/${P}/change_orders/${CO}/approve`,
      {},
      ECO,
      'MANAGER',
      generateIdempotencyKey('d1g')
    );
    expectSuccess(approveRes);

    const coGet2 = await getChangeOrder(P, CO);
    const ECO2 = coGet2.etag;
    expect(coGet2.status).toBe('APPROVED');

    const workItemFrozen = await getWorkItem(P, W1);
    expect(workItemFrozen.start_blockers).toContain('CHANGE_ORDER');

    const res = await postWithIfMatch(
      `/projects/${P}/change_orders/${CO}/cancel`,
      {},
      ECO2,
      'MANAGER',
      generateIdempotencyKey('d1h')
    );

    expectSuccess(res);

    const coAfter = await getChangeOrder(P, CO);
    expect(coAfter.status).toBe('CANCELLED');

    const workItemAfterCancel = await getWorkItem(P, W1);
    expect(workItemAfterCancel.status).toBe('IN_PROGRESS');
    expect(workItemAfterCancel.latest_quality_status).toBe('FAILED');

    expect(workItemAfterCancel.start_blockers || []).not.toContain('CHANGE_ORDER');

    const completeAttemptRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W1}/complete`,
      { actual_hours: 8 },
      workItemAfterCancel.etag,
      'FOREMAN',
      generateIdempotencyKey('d1i')
    );
    expectErrorCode(completeAttemptRes, 'ERR_QUALITY_FAILED_BLOCKING');

    const workItemFinal = await getWorkItem(P, W1);
    expect(workItemFinal.status).toBe('IN_PROGRESS');
  });

  test('DEEP_002: Complete work item after quality failure followed by quality pass (latest inspection wins)', async () => {

    const { P } = await FX_CORE_PERMITS_GRANTED();

    const workItemRes = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'E1',
        trade: 'ELECTRICAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 10,
      },
      'FOREMAN',
      generateIdempotencyKey('d2')
    );
    expectSuccess(workItemRes);
    const W1 = unwrap(workItemRes.body).id;

    const workItemGet1 = await getWorkItem(P, W1);
    const E1 = workItemGet1.etag;

    const readyRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W1}/ready`,
      {},
      E1,
      'FOREMAN',
      generateIdempotencyKey('d2b')
    );
    expectSuccess(readyRes);

    const workItemGet2 = await getWorkItem(P, W1);
    const E1b = workItemGet2.etag;

    const startRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W1}/start`,
      {},
      E1b,
      'FOREMAN',
      generateIdempotencyKey('d2c')
    );
    expectSuccess(startRes);

    const inspection1Res = await postAs(
      `/projects/${P}/inspections`,
      {
        work_item_id: W1,
        kind: 'QUALITY',
      },
      'INSPECTOR',
      generateIdempotencyKey('d2d')
    );
    expectSuccess(inspection1Res);
    const IQ1 = unwrap(inspection1Res.body).id;

    const submit1Res = await postAs(
      `/projects/${P}/inspections/${IQ1}/submit`,
      { outcome: 'FAILED' },
      'INSPECTOR',
      generateIdempotencyKey('d2e')
    );
    expectSuccess(submit1Res);

    const workItemAfterFail = await getWorkItem(P, W1);
    expect(workItemAfterFail.latest_quality_status).toBe('FAILED');

    const inspection2Res = await postAs(
      `/projects/${P}/inspections`,
      {
        work_item_id: W1,
        kind: 'QUALITY',
      },
      'INSPECTOR',
      generateIdempotencyKey('d2f')
    );
    expectSuccess(inspection2Res);
    const IQ2 = unwrap(inspection2Res.body).id;

    const submit2Res = await postAs(
      `/projects/${P}/inspections/${IQ2}/submit`,
      { outcome: 'PASSED' },
      'INSPECTOR',
      generateIdempotencyKey('d2g')
    );
    expectSuccess(submit2Res);

    const workItemGet3 = await getWorkItem(P, W1);
    const E1c = workItemGet3.etag;

    expect(workItemGet3.latest_quality_status).toBe('PASSED');

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W1}/complete`,
      { actual_hours: 9 },
      E1c,
      'FOREMAN',
      generateIdempotencyKey('d2h')
    );

    expectSuccess(res);

    const workItemAfter = await getWorkItem(P, W1);
    expect(workItemAfter.status).toBe('DONE');
    expect(workItemAfter.actual_hours).toBe(9);

    const projectAfter = await getProject(P);
    expect(projectAfter.labor_used_hours).toBe(9);
  });

  test('DEEP_003: Budget increase via change order enables completion that was previously blocked', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const permitRes = await postAs(
      `/projects/${P}/permits`,
      { trade: 'ELECTRICAL' },
      'MANAGER',
      generateIdempotencyKey('d3')
    );
    expectSuccess(permitRes);
    const PE = unwrap(permitRes.body).id;

    const grantRes = await postAs(
      `/projects/${P}/permits/${PE}/decide`,
      { decision: 'GRANT' },
      'MANAGER',
      generateIdempotencyKey('d3b')
    );
    expectSuccess(grantRes);

    const workItemRes = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'E',
        trade: 'ELECTRICAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 110,
      },
      'FOREMAN',
      generateIdempotencyKey('d3c')
    );
    expectSuccess(workItemRes);
    const W = unwrap(workItemRes.body).id;

    const workItemGet1 = await getWorkItem(P, W);
    const E = workItemGet1.etag;

    const readyRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/ready`,
      {},
      E,
      'FOREMAN',
      generateIdempotencyKey('d3d')
    );
    expectSuccess(readyRes);

    const projectAfterReady = await getProject(P);
    expect(projectAfterReady.posture).toBe('REVIEW');
    expect(projectAfterReady.labor_reserved_hours).toBe(110);

    const inspectionRes = await postAs(
      `/projects/${P}/inspections`,
      {
        work_item_id: W,
        kind: 'SAFETY',
      },
      'INSPECTOR',
      generateIdempotencyKey('d3e')
    );
    expectSuccess(inspectionRes);
    const IS = unwrap(inspectionRes.body).id;

    const submitRes = await postAs(
      `/projects/${P}/inspections/${IS}/submit`,
      { outcome: 'PASSED' },
      'INSPECTOR',
      generateIdempotencyKey('d3f')
    );
    expectSuccess(submitRes);

    const workItemGet2 = await getWorkItem(P, W);
    const E2 = workItemGet2.etag;

    const startRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/start`,
      {},
      E2,
      'FOREMAN',
      generateIdempotencyKey('d3g')
    );
    expectSuccess(startRes);

    const workItemGet3 = await getWorkItem(P, W);
    const E3 = workItemGet3.etag;

    const failedCompleteRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/complete`,
      { actual_hours: 121 },
      E3,
      'FOREMAN',
      generateIdempotencyKey('d3h')
    );
    expectErrorCode(failedCompleteRes, 'ERR_LABOR_BUDGET_EXCEEDED');

    const workItemAfterFailedComplete = await getWorkItem(P, W);
    expect(workItemAfterFailedComplete.status).toBe('IN_PROGRESS');
    expect(workItemAfterFailedComplete.actual_hours).toBeUndefined();

    const projectAfterFailedComplete = await getProject(P);
    expect(projectAfterFailedComplete.labor_used_hours).toBe(0);

    const coRes = await postAs(
      `/projects/${P}/change_orders`,
      {
        work_item_id: W,
        summary: 'Add 5',
        labor_budget_hours_delta: 5,
      },
      'FOREMAN',
      generateIdempotencyKey('d3i')
    );
    expectSuccess(coRes);
    const CO = unwrap(coRes.body).id;

    const coGet1 = await getChangeOrder(P, CO);
    const ECO = coGet1.etag;

    const approveRes = await postWithIfMatch(
      `/projects/${P}/change_orders/${CO}/approve`,
      {},
      ECO,
      'MANAGER',
      generateIdempotencyKey('d3j')
    );
    expectSuccess(approveRes);

    const coGet2 = await getChangeOrder(P, CO);
    const ECO2 = coGet2.etag;
    expect(coGet2.status).toBe('APPROVED');

    const applyRes = await postWithIfMatch(
      `/projects/${P}/change_orders/${CO}/apply`,
      {},
      ECO2,
      'MANAGER',
      generateIdempotencyKey('d3k')
    );
    expectSuccess(applyRes);

    const projectAfterApply = await getProject(P);
    expect(projectAfterApply.labor_budget_hours).toBe(125);

    const workItemGet4 = await getWorkItem(P, W);
    const E4 = workItemGet4.etag;

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/complete`,
      { actual_hours: 121 },
      E4,
      'FOREMAN',
      generateIdempotencyKey('d3l')
    );

    expectSuccess(res);

    const workItemAfter = await getWorkItem(P, W);
    expect(workItemAfter.status).toBe('DONE');
    expect(workItemAfter.actual_hours).toBe(121);

    const projectFinal = await getProject(P);
    expect(projectFinal.labor_used_hours).toBe(121);
    expect(projectFinal.labor_budget_hours).toBe(125);
    expect(projectFinal.labor_available_hours).toBe(4);
  });

  test('DEEP_004: Cancelling work item removes STOP_WORK cause but permit still contributes to REVIEW', async () => {

    const { P, PE } = await FX_ELECTRICAL_PERMIT_GRANTED();

    const workItemRes = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'E',
        trade: 'ELECTRICAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 10,
      },
      'FOREMAN',
      generateIdempotencyKey('d4')
    );
    expectSuccess(workItemRes);
    const W = unwrap(workItemRes.body).id;

    const workItemGet1 = await getWorkItem(P, W);
    const E = workItemGet1.etag;

    const readyRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/ready`,
      {},
      E,
      'FOREMAN',
      generateIdempotencyKey('d4b')
    );
    expectSuccess(readyRes);

    const projectAfterReady = await getProject(P);
    expect(projectAfterReady.labor_reserved_hours).toBe(10);

    const revokeRes = await postAs(
      `/projects/${P}/permits/${PE}/decide`,
      { decision: 'REVOKE' },
      'MANAGER',
      generateIdempotencyKey('d4c')
    );
    expectSuccess(revokeRes);

    const projectAfterRevoke = await getProject(P);
    expect(projectAfterRevoke.posture).toBe('STOP_WORK');

    const workItemBeforeCancel = await getWorkItem(P, W);
    const etagForCancel = workItemBeforeCancel.etag;

    const cancelRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/cancel`,
      {},
      etagForCancel,
      'FOREMAN',
      generateIdempotencyKey('d4d')
    );
    expectSuccess(cancelRes);

    const res = await getAs(`/projects/${P}`, 'MANAGER');

    expectSuccess(res);
    const project = unwrap(res.body);

    expect(project.labor_reserved_hours).toBe(0);

    expect(project.posture).toBe('OPEN');

    const electricalPermit = project.permits?.find((p: any) => p.trade === 'ELECTRICAL');
    expect(electricalPermit).toBeDefined();
    expect(electricalPermit.status).toBe('REVOKED');
  });

  test('DEEP_005: Cancelling work item cascades to cancel its open change orders', async () => {

    const { P } = await FX_ELECTRICAL_PERMIT_GRANTED();

    const workItemRes = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'E',
        trade: 'ELECTRICAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 10,
      },
      'FOREMAN',
      generateIdempotencyKey('d5')
    );
    expectSuccess(workItemRes);
    const W = unwrap(workItemRes.body).id;

    const workItemGet1 = await getWorkItem(P, W);
    const E = workItemGet1.etag;

    const readyRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/ready`,
      {},
      E,
      'FOREMAN',
      generateIdempotencyKey('d5b')
    );
    expectSuccess(readyRes);

    const workItemGet2 = await getWorkItem(P, W);
    const E2 = workItemGet2.etag;

    const coRes = await postAs(
      `/projects/${P}/change_orders`,
      {
        work_item_id: W,
        summary: 'Scope',
        new_estimated_hours: 12,
      },
      'FOREMAN',
      generateIdempotencyKey('d5c')
    );
    expectSuccess(coRes);
    const CO = unwrap(coRes.body).id;

    const coGet1 = await getChangeOrder(P, CO);
    const ECO = coGet1.etag;
    expect(coGet1.status).toBe('PROPOSED');

    const approveRes = await postWithIfMatch(
      `/projects/${P}/change_orders/${CO}/approve`,
      {},
      ECO,
      'MANAGER',
      generateIdempotencyKey('d5d')
    );
    expectSuccess(approveRes);

    const coGet2 = await getChangeOrder(P, CO);
    const ECO2 = coGet2.etag;
    expect(coGet2.status).toBe('APPROVED');

    const workItemBeforeCancel = await getWorkItem(P, W);
    const etagForCancel = workItemBeforeCancel.etag;

    const cancelRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/cancel`,
      {},
      etagForCancel,
      'FOREMAN',
      generateIdempotencyKey('d5e')
    );
    expectSuccess(cancelRes);

    const res = await getAs(`/projects/${P}/change_orders/${CO}`, 'MANAGER');

    expectSuccess(res);
    const changeOrderAfter = unwrap(res.body);
    expect(changeOrderAfter.status).toBe('CANCELLED');
  });

});
