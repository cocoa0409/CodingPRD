import { getAs, postAs, postWithIfMatch, generateIdempotencyKey } from '../../../test-helpers/api-client';
import { expectSuccess, expectErrorCode } from '../../../test-helpers/assertions';
import {
  createProject,
  getProject,
  createWorkItem,
  getWorkItem,
  readyWorkItem,
  startWorkItem,
  completeWorkItem,
  cancelWorkItem,
  createPermit,
  decidePermit,
  createInspection,
  submitInspection,
  createChangeOrder,
  getChangeOrder,
  approveChangeOrder,
  applyChangeOrder,
  uniqueId,
  unwrap,
} from '../../../test-helpers/resources';
import {
  FX_PROJECT_OPEN_120,
  FX_READY_ELECTRICAL_ITEM,
  FX_TWO_ACTIVE_QUALITY_FAILS,
} from '../../../test-helpers/fixtures';

describe('Feature 8: Cross-Feature Interaction Tests', () => {

  test('CROSS_001: Replacement permit GRANTED clears STOP_WORK and allows starting work item', async () => {

    const { P, PE, W } = await FX_READY_ELECTRICAL_ITEM();

    const revokeRes = await postAs(
      `/projects/${P}/permits/${PE}/decide`,
      { decision: 'REVOKE' },
      'MANAGER',
      generateIdempotencyKey('c1')
    );
    expectSuccess(revokeRes);

    const projectAfterRevoke = await getProject(P);
    expect(projectAfterRevoke.posture).toBe('STOP_WORK');

    const workItemBeforeRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemBeforeRes);
    const etagBeforeReplacement = unwrap(workItemBeforeRes.body).etag;

    const blockedStartRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/start`,
      {},
      etagBeforeReplacement,
      'FOREMAN',
      generateIdempotencyKey('c1_blocked')
    );
    expectErrorCode(blockedStartRes, 'ERR_POSTURE_BLOCKED');

    const replacementPermitRes = await postAs(
      `/projects/${P}/permits`,
      {
        trade: 'ELECTRICAL',
        replaces_permit_id: PE,
      },
      'MANAGER',
      generateIdempotencyKey('c1b')
    );
    expectSuccess(replacementPermitRes);
    const PE2 = unwrap(replacementPermitRes.body).id;

    const projectAfterReplacement = await getProject(P);
    expect(projectAfterReplacement.posture).not.toBe('STOP_WORK');

    const grantRes = await postAs(
      `/projects/${P}/permits/${PE2}/decide`,
      { decision: 'GRANT' },
      'MANAGER',
      generateIdempotencyKey('c1c')
    );
    expectSuccess(grantRes);

    const workItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemRes);
    const E = unwrap(workItemRes.body).etag;

    const projectAfterGrant = await getProject(P);
    expect(projectAfterGrant.posture).not.toBe('STOP_WORK');

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/start`,
      {},
      E,
      'FOREMAN',
      generateIdempotencyKey('c1d')
    );

    expectSuccess(res);

    const workItemAfter = await getWorkItem(P, W);
    expect(workItemAfter.status).toBe('IN_PROGRESS');

    const projectFinal = await getProject(P);
    expect(projectFinal.posture).not.toBe('STOP_WORK');
  });

  test('CROSS_002: DRAFT work item is not startable and permit affects transition to READY', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const workItemRes = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'Elec',
        trade: 'ELECTRICAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 5,
      },
      'FOREMAN',
      generateIdempotencyKey('c2')
    );
    expectSuccess(workItemRes);
    const W = unwrap(workItemRes.body).id;

    const getWorkItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(getWorkItemRes);
    const workItem = unwrap(getWorkItemRes.body);
    const E = workItem.etag;

    expect(workItem.status).toBe('DRAFT');
    expect(workItem.is_startable).toBe(false);

    const readyWithoutPermitRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/ready`,
      {},
      E,
      'FOREMAN',
      generateIdempotencyKey('c2_nopermit')
    );
    expectErrorCode(readyWithoutPermitRes, 'ERR_PERMIT_REQUIRED');

    const permitRes = await postAs(
      `/projects/${P}/permits`,
      { trade: 'ELECTRICAL' },
      'MANAGER',
      generateIdempotencyKey('c2b')
    );
    expectSuccess(permitRes);
    const PE = unwrap(permitRes.body).id;

    const grantRes = await postAs(
      `/projects/${P}/permits/${PE}/decide`,
      { decision: 'GRANT' },
      'MANAGER',
      generateIdempotencyKey('c2c')
    );
    expectSuccess(grantRes);

    const res = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');

    expectSuccess(res);
    const workItemAfter = unwrap(res.body);
    expect(workItemAfter.status).toBe('DRAFT');
    expect(workItemAfter.is_startable).toBe(false);

    const readyWithPermitRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/ready`,
      {},
      workItemAfter.etag,
      'FOREMAN',
      generateIdempotencyKey('c2d')
    );
    expectSuccess(readyWithPermitRes);

    const workItemReady = await getWorkItem(P, W);
    expect(workItemReady.status).toBe('READY');
  });

  test('CROSS_003: Completing work with lower actual_hours frees budget and lifts REVIEW posture', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const workItemRes = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'General102',
        trade: 'GENERAL',
        zone: 'ZONE_C',
        criticality: 'STANDARD',
        estimated_hours: 102,
      },
      'FOREMAN',
      generateIdempotencyKey('c3')
    );
    expectSuccess(workItemRes);
    const W = unwrap(workItemRes.body).id;

    let workItemGet = await getWorkItem(P, W);
    let E = workItemGet.etag;

    const readyRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/ready`,
      {},
      E,
      'FOREMAN',
      generateIdempotencyKey('c3b')
    );
    expectSuccess(readyRes);

    const projectAfterReady = await getProject(P);
    expect(projectAfterReady.posture).toBe('REVIEW');
    expect(projectAfterReady.labor_reserved_hours).toBe(102);

    const inspectionRes = await postAs(
      `/projects/${P}/inspections`,
      {
        work_item_id: W,
        kind: 'SAFETY',
      },
      'INSPECTOR',
      generateIdempotencyKey('c3c')
    );
    expectSuccess(inspectionRes);
    const IS = unwrap(inspectionRes.body).id;

    workItemGet = await getWorkItem(P, W);
    const etagBeforeSafety = workItemGet.etag;

    expect(workItemGet.is_startable).toBe(false);
    expect(workItemGet.start_blockers).toContain('SAFETY');

    const submitRes = await postAs(
      `/projects/${P}/inspections/${IS}/submit`,
      { outcome: 'PASSED' },
      'INSPECTOR',
      generateIdempotencyKey('c3d')
    );
    expectSuccess(submitRes);

    workItemGet = await getWorkItem(P, W);
    let E2 = workItemGet.etag;
    expect(workItemGet.latest_safety_status).toBe('PASSED');

    const startRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/start`,
      {},
      E2,
      'FOREMAN',
      generateIdempotencyKey('c3e')
    );
    expectSuccess(startRes);

    const projectAfterStart = await getProject(P);
    expect(projectAfterStart.labor_reserved_hours).toBe(0);
    expect(projectAfterStart.labor_committed_hours).toBe(102);

    workItemGet = await getWorkItem(P, W);
    let E3 = workItemGet.etag;

    const completeRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/complete`,
      { actual_hours: 70 },
      E3,
      'FOREMAN',
      generateIdempotencyKey('c3f')
    );
    expectSuccess(completeRes);

    const res = await getAs(`/projects/${P}`, 'MANAGER');

    expectSuccess(res);
    const project = unwrap(res.body);
    expect(project.labor_used_hours).toBe(70);
    expect(project.labor_available_hours).toBe(50);
    expect(project.labor_reserved_hours).toBe(0);
    expect(project.labor_committed_hours).toBe(0);
    expect(project.posture).toBe('OPEN');
  });

  test('CROSS_004: Cancelling work item with failed quality recalculates posture away from REVIEW', async () => {

    const { P, W1, EW1b, W2, I1, I2 } = await FX_TWO_ACTIVE_QUALITY_FAILS();

    const projectBefore = await getProject(P);
    expect(projectBefore.posture).toBe('REVIEW');

    const workItem1Get = await getWorkItem(P, W1);
    const currentEtag = workItem1Get.etag;

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W1}/cancel`,
      {},
      currentEtag,
      'FOREMAN',
      generateIdempotencyKey('c4')
    );

    expectSuccess(res);

    const workItem1After = await getWorkItem(P, W1);
    expect(workItem1After.status).toBe('CANCELLED');

    const projectAfter = await getProject(P);
    expect(projectAfter.posture).not.toBe('REVIEW');

    expect(projectAfter.posture).toBe('OPEN');
  });

  test('CROSS_005: Applying change order with scope+budget increases budget and resets work item to DRAFT', async () => {

    const { P, W } = await FX_READY_ELECTRICAL_ITEM();

    const projectBefore = await getProject(P);
    const initialBudget = projectBefore.labor_budget_hours;
    expect(initialBudget).toBe(120);
    expect(projectBefore.labor_reserved_hours).toBe(10);

    const coRes = await postAs(
      `/projects/${P}/change_orders`,
      {
        work_item_id: W,
        summary: 'Scope+Budget',
        labor_budget_hours_delta: 10,
        new_estimated_hours: 20,
      },
      'FOREMAN',
      generateIdempotencyKey('c5')
    );
    expectSuccess(coRes);
    const CO = unwrap(coRes.body).id;

    let coGet = await getChangeOrder(P, CO);
    const E = coGet.etag;

    const approveRes = await postWithIfMatch(
      `/projects/${P}/change_orders/${CO}/approve`,
      {},
      E,
      'MANAGER',
      generateIdempotencyKey('c5b')
    );
    expectSuccess(approveRes);

    coGet = await getChangeOrder(P, CO);
    const E2 = coGet.etag;
    expect(coGet.status).toBe('APPROVED');

    const workItemFrozen = await getWorkItem(P, W);
    expect(workItemFrozen.is_startable).toBe(false);
    expect(workItemFrozen.start_blockers).toContain('CHANGE_ORDER');

    const startFrozenRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/start`,
      {},
      workItemFrozen.etag,
      'FOREMAN',
      generateIdempotencyKey('c5_frozen')
    );
    expectErrorCode(startFrozenRes, 'ERR_WORK_ITEM_FROZEN');

    const res = await postWithIfMatch(
      `/projects/${P}/change_orders/${CO}/apply`,
      {},
      E2,
      'MANAGER',
      generateIdempotencyKey('c5c')
    );

    expectSuccess(res);

    const coAfter = await getChangeOrder(P, CO);
    expect(coAfter.status).toBe('APPLIED');

    const projectAfter = await getProject(P);
    expect(projectAfter.labor_budget_hours).toBe(130);

    expect(projectAfter.labor_reserved_hours).toBe(0);

    const workItemAfter = await getWorkItem(P, W);
    expect(workItemAfter.status).toBe('DRAFT');
    expect(workItemAfter.estimated_hours).toBe(20);
  });

});
