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
  createPermit,
  decidePermit,
  createInspection,
  submitInspection,
  createChangeOrder,
  getChangeOrder,
  approveChangeOrder,
  applyChangeOrder,
  cancelChangeOrder,
  uniqueId,
  unwrap,
} from '../../../test-helpers/resources';
import {
  FX_PROJECT_OPEN_120,
  FX_READY_ELECTRICAL_ITEM,
  FX_INPROGRESS_ELECTRICAL_ITEM,
  FX_APPROVED_SCOPE_CO_ON_READY_ELECTRICAL,
  FX_APPROVED_BUDGETONLY_CO_ON_INPROGRESS_ELECTRICAL,
} from '../../../test-helpers/fixtures';

describe('Feature 5: Change Order Tests', () => {

  test('CO_001: FOREMAN can create change order with labor_budget_hours_delta', async () => {

    const { P, W } = await FX_READY_ELECTRICAL_ITEM();

    const res = await postAs(
      `/projects/${P}/change_orders`,
      {
        work_item_id: W,
        summary: 'Add hours',
        labor_budget_hours_delta: 10,
      },
      'FOREMAN',
      generateIdempotencyKey('co1')
    );

    expectSuccess(res);
    const changeOrder = unwrap(res.body);
    expect(changeOrder.status).toBe('PROPOSED');
    expect(changeOrder.id).toBeDefined();
    expect(changeOrder.work_item_id).toBe(W);
    expect(changeOrder.summary).toBe('Add hours');
    expect(changeOrder.labor_budget_hours_delta).toBe(10);

    const projectRes = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(projectRes);
    expect(unwrap(projectRes.body).labor_budget_hours).toBe(120);
  });

  test('CO_002: INSPECTOR cannot create change order (ERR_FORBIDDEN)', async () => {

    const { P, W } = await FX_READY_ELECTRICAL_ITEM();

    const res = await postAs(
      `/projects/${P}/change_orders`,
      {
        work_item_id: W,
        summary: 'Nope',
        labor_budget_hours_delta: 10,
      },
      'INSPECTOR',
      generateIdempotencyKey('co2')
    );

    expectErrorCode(res, 'ERR_FORBIDDEN');
  });

  test('CO_003: Second open change order on same work item fails with ERR_CHANGE_ORDER_CONFLICT', async () => {

    const { P, W } = await FX_READY_ELECTRICAL_ITEM();

    const firstRes = await postAs(
      `/projects/${P}/change_orders`,
      {
        work_item_id: W,
        summary: 'First',
        labor_budget_hours_delta: 1,
      },
      'FOREMAN',
      generateIdempotencyKey('co3')
    );
    expectSuccess(firstRes);
    const CO1 = unwrap(firstRes.body).id;

    const res = await postAs(
      `/projects/${P}/change_orders`,
      {
        work_item_id: W,
        summary: 'Second',
        labor_budget_hours_delta: 1,
      },
      'FOREMAN',
      generateIdempotencyKey('co3b')
    );

    expectErrorCode(res, 'ERR_CHANGE_ORDER_CONFLICT');

    const coRes = await getAs(`/projects/${P}/change_orders/${CO1}`, 'FOREMAN');
    expectSuccess(coRes);
    expect(unwrap(coRes.body).status).toBe('PROPOSED');
  });

  test('CO_004: MANAGER can approve change order', async () => {

    const { P, W } = await FX_READY_ELECTRICAL_ITEM();

    const coRes = await postAs(
      `/projects/${P}/change_orders`,
      {
        work_item_id: W,
        summary: 'Scope',
        new_zone: 'ZONE_B',
        new_estimated_hours: 12,
      },
      'FOREMAN',
      generateIdempotencyKey('co4')
    );
    expectSuccess(coRes);
    const CO = unwrap(coRes.body).id;

    const getCoRes = await getAs(`/projects/${P}/change_orders/${CO}`, 'FOREMAN');
    expectSuccess(getCoRes);
    const E = unwrap(getCoRes.body).etag;

    const res = await postWithIfMatch(
      `/projects/${P}/change_orders/${CO}/approve`,
      {},
      E,
      'MANAGER',
      generateIdempotencyKey('co4b')
    );

    expectSuccess(res);

    const finalCoRes = await getAs(`/projects/${P}/change_orders/${CO}`, 'FOREMAN');
    expectSuccess(finalCoRes);
    expect(unwrap(finalCoRes.body).status).toBe('APPROVED');

    const workItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemRes);
    const workItem = unwrap(workItemRes.body);
    expect(workItem.start_blockers).toContain('CHANGE_ORDER');
    expect(workItem.is_startable).toBe(false);
  });

  test('CO_005: FOREMAN cannot approve change order (ERR_FORBIDDEN)', async () => {

    const { P, W } = await FX_READY_ELECTRICAL_ITEM();

    const coRes = await postAs(
      `/projects/${P}/change_orders`,
      {
        work_item_id: W,
        summary: 'Scope',
        new_zone: 'ZONE_B',
        new_estimated_hours: 12,
      },
      'FOREMAN',
      generateIdempotencyKey('co5')
    );
    expectSuccess(coRes);
    const CO = unwrap(coRes.body).id;

    const getCoRes = await getAs(`/projects/${P}/change_orders/${CO}`, 'FOREMAN');
    expectSuccess(getCoRes);
    const E = unwrap(getCoRes.body).etag;

    const res = await postWithIfMatch(
      `/projects/${P}/change_orders/${CO}/approve`,
      {},
      E,
      'FOREMAN',
      generateIdempotencyKey('co5b')
    );

    expectErrorCode(res, 'ERR_FORBIDDEN');

    const finalCoRes = await getAs(`/projects/${P}/change_orders/${CO}`, 'FOREMAN');
    expectSuccess(finalCoRes);
    expect(unwrap(finalCoRes.body).status).toBe('PROPOSED');
  });

  test('CO_006: Approve without If-Match fails with ERR_MISSING_IF_MATCH', async () => {

    const { P, W } = await FX_READY_ELECTRICAL_ITEM();

    const coRes = await postAs(
      `/projects/${P}/change_orders`,
      {
        work_item_id: W,
        summary: 'Scope',
        new_zone: 'ZONE_B',
        new_estimated_hours: 12,
      },
      'FOREMAN',
      generateIdempotencyKey('co6')
    );
    expectSuccess(coRes);
    const CO = unwrap(coRes.body).id;

    const res = await postAs(
      `/projects/${P}/change_orders/${CO}/approve`,
      {},
      'MANAGER',
      generateIdempotencyKey('co6b')
    );

    expectErrorCode(res, 'ERR_MISSING_IF_MATCH');

    const finalCoRes = await getAs(`/projects/${P}/change_orders/${CO}`, 'FOREMAN');
    expectSuccess(finalCoRes);
    expect(unwrap(finalCoRes.body).status).toBe('PROPOSED');
  });

  test('CO_007: Starting frozen work item fails with ERR_WORK_ITEM_FROZEN', async () => {

    const { P, W } = await FX_APPROVED_SCOPE_CO_ON_READY_ELECTRICAL();

    const workItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemRes);
    const workItemBefore = unwrap(workItemRes.body);
    const etag = workItemBefore.etag;

    expect(workItemBefore.is_startable).toBe(false);
    expect(workItemBefore.start_blockers).toContain('CHANGE_ORDER');

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/start`,
      {},
      etag,
      'FOREMAN',
      generateIdempotencyKey('co7')
    );

    expectErrorCode(res, 'ERR_WORK_ITEM_FROZEN');

    const finalWorkItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(finalWorkItemRes);
    const finalWorkItem = unwrap(finalWorkItemRes.body);
    expect(finalWorkItem.status).toBe('READY');
    expect(finalWorkItem.is_startable).toBe(false);
    expect(finalWorkItem.start_blockers).toContain('CHANGE_ORDER');
  });

  test('CO_008: FOREMAN cannot apply change order (ERR_FORBIDDEN)', async () => {

    const { P, CO, ECO2 } = await FX_APPROVED_SCOPE_CO_ON_READY_ELECTRICAL();

    const res = await postWithIfMatch(
      `/projects/${P}/change_orders/${CO}/apply`,
      {},
      ECO2,
      'FOREMAN',
      generateIdempotencyKey('co8')
    );

    expectErrorCode(res, 'ERR_FORBIDDEN');

    const coRes = await getAs(`/projects/${P}/change_orders/${CO}`, 'FOREMAN');
    expectSuccess(coRes);
    expect(unwrap(coRes.body).status).toBe('APPROVED');
  });

  test('CO_009: Applying scope change resets work item to DRAFT and releases reserved hours', async () => {

    const { P, W, CO, ECO2 } = await FX_APPROVED_SCOPE_CO_ON_READY_ELECTRICAL();

    const res = await postWithIfMatch(
      `/projects/${P}/change_orders/${CO}/apply`,
      {},
      ECO2,
      'MANAGER',
      generateIdempotencyKey('co9')
    );

    expectSuccess(res);

    const coRes = await getAs(`/projects/${P}/change_orders/${CO}`, 'FOREMAN');
    expectSuccess(coRes);
    expect(unwrap(coRes.body).status).toBe('APPLIED');

    const workItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemRes);
    const workItem = unwrap(workItemRes.body);
    expect(workItem.status).toBe('DRAFT');
    expect(workItem.zone).toBe('ZONE_B');
    expect(workItem.estimated_hours).toBe(12);

    const projectRes = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(projectRes);
    const project = unwrap(projectRes.body);
    expect(project.labor_reserved_hours).toBe(0);
    expect(project.labor_available_hours).toBe(120);
  });

  test('CO_010: Scope change on IN_PROGRESS work item fails with ERR_SCOPE_CHANGE_NOT_ALLOWED', async () => {

    const { P, W } = await FX_INPROGRESS_ELECTRICAL_ITEM();

    const coRes = await postAs(
      `/projects/${P}/change_orders`,
      {
        work_item_id: W,
        summary: 'Scope midflight',
        new_zone: 'ZONE_B',
      },
      'FOREMAN',
      generateIdempotencyKey('co10')
    );
    expectSuccess(coRes);
    const CO = unwrap(coRes.body).id;

    const getCoRes = await getAs(`/projects/${P}/change_orders/${CO}`, 'FOREMAN');
    expectSuccess(getCoRes);
    const E = unwrap(getCoRes.body).etag;

    const approveRes = await postWithIfMatch(
      `/projects/${P}/change_orders/${CO}/approve`,
      {},
      E,
      'MANAGER',
      generateIdempotencyKey('co10b')
    );
    expectSuccess(approveRes);

    const getCoRes2 = await getAs(`/projects/${P}/change_orders/${CO}`, 'FOREMAN');
    expectSuccess(getCoRes2);
    const E2 = unwrap(getCoRes2.body).etag;

    const res = await postWithIfMatch(
      `/projects/${P}/change_orders/${CO}/apply`,
      {},
      E2,
      'MANAGER',
      generateIdempotencyKey('co10c')
    );

    expectErrorCode(res, 'ERR_SCOPE_CHANGE_NOT_ALLOWED');

    const finalCoRes = await getAs(`/projects/${P}/change_orders/${CO}`, 'FOREMAN');
    expectSuccess(finalCoRes);
    expect(unwrap(finalCoRes.body).status).toBe('APPROVED');

    const workItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemRes);
    expect(unwrap(workItemRes.body).status).toBe('IN_PROGRESS');
  });

  test('CO_011: Applying budget-only change order updates labor_budget_hours', async () => {

    const { P, W, COB, ECOB2 } = await FX_APPROVED_BUDGETONLY_CO_ON_INPROGRESS_ELECTRICAL();

    const res = await postWithIfMatch(
      `/projects/${P}/change_orders/${COB}/apply`,
      {},
      ECOB2,
      'MANAGER',
      generateIdempotencyKey('co11')
    );

    expectSuccess(res);

    const coRes = await getAs(`/projects/${P}/change_orders/${COB}`, 'FOREMAN');
    expectSuccess(coRes);
    expect(unwrap(coRes.body).status).toBe('APPLIED');

    const projectRes = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(projectRes);
    const project = unwrap(projectRes.body);
    expect(project.labor_budget_hours).toBe(140);

    expect(project.labor_available_hours).toBeGreaterThan(0);

    const workItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemRes);
    expect(unwrap(workItemRes.body).status).toBe('IN_PROGRESS');
  });

  test('CO_012: Budget change order application restores posture from REVIEW to OPEN', async () => {

    const { P, project } = await FX_PROJECT_OPEN_120();

    const workItemRes = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'Hold60',
        trade: 'GENERAL',
        zone: 'ZONE_C',
        criticality: 'STANDARD',
        estimated_hours: 60,
      },
      'FOREMAN',
      generateIdempotencyKey('co12')
    );
    expectSuccess(workItemRes);
    const W = unwrap(workItemRes.body).id;

    const getW1Res = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(getW1Res);
    const E = unwrap(getW1Res.body).etag;

    const readyRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/ready`,
      {},
      E,
      'FOREMAN',
      generateIdempotencyKey('co12b')
    );
    expectSuccess(readyRes);

    const getW2Res = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(getW2Res);
    const E2 = unwrap(getW2Res.body).etag;

    const startRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/start`,
      {},
      E2,
      'FOREMAN',
      generateIdempotencyKey('co12c')
    );
    expectSuccess(startRes);

    const getW3Res = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(getW3Res);
    const E3 = unwrap(getW3Res.body).etag;

    const completeRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/complete`,
      { actual_hours: 110 },
      E3,
      'FOREMAN',
      generateIdempotencyKey('co12d')
    );
    expectSuccess(completeRes);

    const projectAfterComplete = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(projectAfterComplete);
    const proj1 = unwrap(projectAfterComplete.body);
    expect(proj1.labor_used_hours).toBe(110);
    expect(proj1.labor_available_hours).toBe(10);
    expect(proj1.posture).toBe('REVIEW');

    const coRes = await postAs(
      `/projects/${P}/change_orders`,
      {
        work_item_id: W,
        summary: 'More budget',
        labor_budget_hours_delta: 15,
      },
      'FOREMAN',
      generateIdempotencyKey('co12e')
    );
    expectSuccess(coRes);
    const CO = unwrap(coRes.body).id;

    const getCoRes = await getAs(`/projects/${P}/change_orders/${CO}`, 'FOREMAN');
    expectSuccess(getCoRes);
    const ECO = unwrap(getCoRes.body).etag;

    const approveRes = await postWithIfMatch(
      `/projects/${P}/change_orders/${CO}/approve`,
      {},
      ECO,
      'MANAGER',
      generateIdempotencyKey('co12f')
    );
    expectSuccess(approveRes);

    const getCoRes2 = await getAs(`/projects/${P}/change_orders/${CO}`, 'FOREMAN');
    expectSuccess(getCoRes2);
    const ECO2 = unwrap(getCoRes2.body).etag;

    const res = await postWithIfMatch(
      `/projects/${P}/change_orders/${CO}/apply`,
      {},
      ECO2,
      'MANAGER',
      generateIdempotencyKey('co12g')
    );

    expectSuccess(res);

    const finalProjectRes = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(finalProjectRes);
    const finalProject = unwrap(finalProjectRes.body);
    expect(finalProject.labor_budget_hours).toBe(135);
    expect(finalProject.labor_available_hours).toBe(25);
    expect(finalProject.posture).toBe('OPEN');
  });

  test('CO_013: Negative budget delta that would go below reserved/used fails with ERR_LABOR_BUDGET_EXCEEDED', async () => {

    const { P, project } = await FX_PROJECT_OPEN_120();

    const workItemRes = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'Reserve50',
        trade: 'GENERAL',
        zone: 'ZONE_C',
        criticality: 'STANDARD',
        estimated_hours: 50,
      },
      'FOREMAN',
      generateIdempotencyKey('co13')
    );
    expectSuccess(workItemRes);
    const W = unwrap(workItemRes.body).id;

    const getWRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(getWRes);
    const E = unwrap(getWRes.body).etag;

    const readyRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/ready`,
      {},
      E,
      'FOREMAN',
      generateIdempotencyKey('co13b')
    );
    expectSuccess(readyRes);

    const projectAfterReady = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(projectAfterReady);
    expect(unwrap(projectAfterReady.body).labor_reserved_hours).toBe(50);
    expect(unwrap(projectAfterReady.body).labor_available_hours).toBe(70);

    const coRes = await postAs(
      `/projects/${P}/change_orders`,
      {
        work_item_id: W,
        summary: 'Cut budget',
        labor_budget_hours_delta: -80,
      },
      'FOREMAN',
      generateIdempotencyKey('co13c')
    );
    expectSuccess(coRes);
    const CO = unwrap(coRes.body).id;

    const getCoRes = await getAs(`/projects/${P}/change_orders/${CO}`, 'FOREMAN');
    expectSuccess(getCoRes);
    const ECO = unwrap(getCoRes.body).etag;

    const approveRes = await postWithIfMatch(
      `/projects/${P}/change_orders/${CO}/approve`,
      {},
      ECO,
      'MANAGER',
      generateIdempotencyKey('co13d')
    );
    expectSuccess(approveRes);

    const getCoRes2 = await getAs(`/projects/${P}/change_orders/${CO}`, 'FOREMAN');
    expectSuccess(getCoRes2);
    const ECO2 = unwrap(getCoRes2.body).etag;

    const res = await postWithIfMatch(
      `/projects/${P}/change_orders/${CO}/apply`,
      {},
      ECO2,
      'MANAGER',
      generateIdempotencyKey('co13e')
    );

    expectErrorCode(res, 'ERR_LABOR_BUDGET_EXCEEDED');

    const finalProjectRes = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(finalProjectRes);
    expect(unwrap(finalProjectRes.body).labor_budget_hours).toBe(120);

    const workItemAfterRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemAfterRes);
    expect(unwrap(workItemAfterRes.body).status).toBe('READY');

    const coAfterRes = await getAs(`/projects/${P}/change_orders/${CO}`, 'FOREMAN');
    expectSuccess(coAfterRes);
    expect(unwrap(coAfterRes.body).status).toBe('APPROVED');
  });

  test('CO_014: Applying scope change voids inspection trail for posture purposes', async () => {

    const { P, W, CO, ECO2 } = await FX_APPROVED_SCOPE_CO_ON_READY_ELECTRICAL();

    const inspectionRes = await postAs(
      `/projects/${P}/inspections`,
      {
        work_item_id: W,
        kind: 'QUALITY',
      },
      'INSPECTOR',
      generateIdempotencyKey('co14')
    );
    expectSuccess(inspectionRes);
    const IQ = unwrap(inspectionRes.body).id;

    const submitRes = await postAs(
      `/projects/${P}/inspections/${IQ}/submit`,
      { outcome: 'FAILED' },
      'INSPECTOR',
      generateIdempotencyKey('co14b')
    );
    expectSuccess(submitRes);

    const workItemBeforeRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemBeforeRes);
    expect(unwrap(workItemBeforeRes.body).latest_quality_status).toBe('FAILED');

    const projectBeforeRes = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(projectBeforeRes);
    expect(unwrap(projectBeforeRes.body).posture).toBe('OPEN');

    const res = await postWithIfMatch(
      `/projects/${P}/change_orders/${CO}/apply`,
      {},
      ECO2,
      'MANAGER',
      generateIdempotencyKey('co14c')
    );

    expectSuccess(res);

    const coAfterRes = await getAs(`/projects/${P}/change_orders/${CO}`, 'FOREMAN');
    expectSuccess(coAfterRes);
    expect(unwrap(coAfterRes.body).status).toBe('APPLIED');

    const workItemAfterRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemAfterRes);
    const workItemAfter = unwrap(workItemAfterRes.body);
    expect(workItemAfter.status).toBe('DRAFT');

    expect(workItemAfter.latest_quality_status == null || workItemAfter.latest_quality_status === undefined).toBe(true);
    expect(workItemAfter.latest_safety_status == null || workItemAfter.latest_safety_status === undefined).toBe(true);
  });

  test('CO_015: Cancelling approved change order unfreezes work item', async () => {

    const { P, W, CO, ECO2 } = await FX_APPROVED_SCOPE_CO_ON_READY_ELECTRICAL();

    const res = await postWithIfMatch(
      `/projects/${P}/change_orders/${CO}/cancel`,
      {},
      ECO2,
      'MANAGER',
      generateIdempotencyKey('co15')
    );

    expectSuccess(res);

    const coRes = await getAs(`/projects/${P}/change_orders/${CO}`, 'FOREMAN');
    expectSuccess(coRes);
    expect(unwrap(coRes.body).status).toBe('CANCELLED');

    const workItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemRes);
    const workItem = unwrap(workItemRes.body);

    expect(workItem.start_blockers).not.toContain('CHANGE_ORDER');

    expect(workItem.is_startable).toBe(true);
    expect(workItem.start_blockers).toHaveLength(0);
  });

  test('CO_016: Applying cancelled change order fails with ERR_CHANGE_ORDER_NOT_APPROVED', async () => {

    const { P, CO, ECO2 } = await FX_APPROVED_SCOPE_CO_ON_READY_ELECTRICAL();

    const cancelRes = await postWithIfMatch(
      `/projects/${P}/change_orders/${CO}/cancel`,
      {},
      ECO2,
      'MANAGER',
      generateIdempotencyKey('co16')
    );
    expectSuccess(cancelRes);

    const getCoRes = await getAs(`/projects/${P}/change_orders/${CO}`, 'FOREMAN');
    expectSuccess(getCoRes);
    const newEtag = unwrap(getCoRes.body).etag;

    const res = await postWithIfMatch(
      `/projects/${P}/change_orders/${CO}/apply`,
      {},
      newEtag,
      'MANAGER',
      generateIdempotencyKey('co16b')
    );

    expectErrorCode(res, 'ERR_CHANGE_ORDER_NOT_APPROVED');

    const finalCoRes = await getAs(`/projects/${P}/change_orders/${CO}`, 'FOREMAN');
    expectSuccess(finalCoRes);
    expect(unwrap(finalCoRes.body).status).toBe('CANCELLED');
  });

  test('CO_017: Applying PROPOSED change order fails with ERR_CHANGE_ORDER_NOT_APPROVED', async () => {

    const { P, W } = await FX_READY_ELECTRICAL_ITEM();

    const coRes = await postAs(
      `/projects/${P}/change_orders`,
      {
        work_item_id: W,
        summary: 'Budget',
        labor_budget_hours_delta: 5,
      },
      'FOREMAN',
      generateIdempotencyKey('co17')
    );
    expectSuccess(coRes);
    const CO = unwrap(coRes.body).id;

    const getCoRes = await getAs(`/projects/${P}/change_orders/${CO}`, 'FOREMAN');
    expectSuccess(getCoRes);
    const E = unwrap(getCoRes.body).etag;

    const res = await postWithIfMatch(
      `/projects/${P}/change_orders/${CO}/apply`,
      {},
      E,
      'MANAGER',
      generateIdempotencyKey('co17b')
    );

    expectErrorCode(res, 'ERR_CHANGE_ORDER_NOT_APPROVED');

    const finalCoRes = await getAs(`/projects/${P}/change_orders/${CO}`, 'FOREMAN');
    expectSuccess(finalCoRes);
    expect(unwrap(finalCoRes.body).status).toBe('PROPOSED');
  });

  test('CO_018: Approving already APPLIED change order fails with ERR_INVALID_STATE', async () => {

    const { P, W } = await FX_READY_ELECTRICAL_ITEM();

    const coRes = await postAs(
      `/projects/${P}/change_orders`,
      {
        work_item_id: W,
        summary: 'Budget',
        labor_budget_hours_delta: 5,
      },
      'FOREMAN',
      generateIdempotencyKey('co18')
    );
    expectSuccess(coRes);
    const CO = unwrap(coRes.body).id;

    const getCoRes = await getAs(`/projects/${P}/change_orders/${CO}`, 'FOREMAN');
    expectSuccess(getCoRes);
    const E = unwrap(getCoRes.body).etag;

    const approveRes = await postWithIfMatch(
      `/projects/${P}/change_orders/${CO}/approve`,
      {},
      E,
      'MANAGER',
      generateIdempotencyKey('co18b')
    );
    expectSuccess(approveRes);

    const getCoRes2 = await getAs(`/projects/${P}/change_orders/${CO}`, 'FOREMAN');
    expectSuccess(getCoRes2);
    const E2 = unwrap(getCoRes2.body).etag;

    const applyRes = await postWithIfMatch(
      `/projects/${P}/change_orders/${CO}/apply`,
      {},
      E2,
      'MANAGER',
      generateIdempotencyKey('co18c')
    );
    expectSuccess(applyRes);

    const getCoRes3 = await getAs(`/projects/${P}/change_orders/${CO}`, 'FOREMAN');
    expectSuccess(getCoRes3);
    const E3 = unwrap(getCoRes3.body).etag;

    const res = await postWithIfMatch(
      `/projects/${P}/change_orders/${CO}/approve`,
      {},
      E3,
      'MANAGER',
      generateIdempotencyKey('co18d')
    );

    expectErrorCode(res, 'ERR_INVALID_STATE');

    const finalCoRes = await getAs(`/projects/${P}/change_orders/${CO}`, 'FOREMAN');
    expectSuccess(finalCoRes);
    expect(unwrap(finalCoRes.body).status).toBe('APPLIED');
  });

  test('CO_019: Applying scope change with new_trade changes trade and resets to DRAFT', async () => {

    const { P, W } = await FX_READY_ELECTRICAL_ITEM();

    const coRes = await postAs(
      `/projects/${P}/change_orders`,
      {
        work_item_id: W,
        summary: 'Scope',
        new_trade: 'PLUMBING',
      },
      'FOREMAN',
      generateIdempotencyKey('co19')
    );
    expectSuccess(coRes);
    const CO = unwrap(coRes.body).id;

    const getCoRes = await getAs(`/projects/${P}/change_orders/${CO}`, 'FOREMAN');
    expectSuccess(getCoRes);
    const E = unwrap(getCoRes.body).etag;

    const approveRes = await postWithIfMatch(
      `/projects/${P}/change_orders/${CO}/approve`,
      {},
      E,
      'MANAGER',
      generateIdempotencyKey('co19b')
    );
    expectSuccess(approveRes);

    const getCoRes2 = await getAs(`/projects/${P}/change_orders/${CO}`, 'FOREMAN');
    expectSuccess(getCoRes2);
    const E2 = unwrap(getCoRes2.body).etag;

    const res = await postWithIfMatch(
      `/projects/${P}/change_orders/${CO}/apply`,
      {},
      E2,
      'MANAGER',
      generateIdempotencyKey('co19c')
    );

    expectSuccess(res);

    const coAfterRes = await getAs(`/projects/${P}/change_orders/${CO}`, 'FOREMAN');
    expectSuccess(coAfterRes);
    expect(unwrap(coAfterRes.body).status).toBe('APPLIED');

    const workItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemRes);
    const workItem = unwrap(workItemRes.body);
    expect(workItem.trade).toBe('PLUMBING');
    expect(workItem.status).toBe('DRAFT');

    expect(workItem.zone).toBe('ZONE_A');
    expect(workItem.criticality).toBe('STANDARD');
  });

  test('CO_020: Work item with new trade requires permit to become READY', async () => {

    const { P, W } = await FX_READY_ELECTRICAL_ITEM();

    const coRes = await postAs(
      `/projects/${P}/change_orders`,
      {
        work_item_id: W,
        summary: 'Scope',
        new_trade: 'PLUMBING',
      },
      'FOREMAN',
      generateIdempotencyKey('co20')
    );
    expectSuccess(coRes);
    const CO = unwrap(coRes.body).id;

    const getCoRes = await getAs(`/projects/${P}/change_orders/${CO}`, 'FOREMAN');
    expectSuccess(getCoRes);
    const E = unwrap(getCoRes.body).etag;

    const approveRes = await postWithIfMatch(
      `/projects/${P}/change_orders/${CO}/approve`,
      {},
      E,
      'MANAGER',
      generateIdempotencyKey('co20b')
    );
    expectSuccess(approveRes);

    const getCoRes2 = await getAs(`/projects/${P}/change_orders/${CO}`, 'FOREMAN');
    expectSuccess(getCoRes2);
    const E2 = unwrap(getCoRes2.body).etag;

    const applyRes = await postWithIfMatch(
      `/projects/${P}/change_orders/${CO}/apply`,
      {},
      E2,
      'MANAGER',
      generateIdempotencyKey('co20c')
    );
    expectSuccess(applyRes);

    const getWRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(getWRes);
    const EWnew = unwrap(getWRes.body).etag;
    expect(unwrap(getWRes.body).trade).toBe('PLUMBING');
    expect(unwrap(getWRes.body).status).toBe('DRAFT');

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/ready`,
      {},
      EWnew,
      'FOREMAN',
      generateIdempotencyKey('co20d')
    );

    expectErrorCode(res, 'ERR_PERMIT_REQUIRED');

    const finalWorkItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(finalWorkItemRes);
    expect(unwrap(finalWorkItemRes.body).status).toBe('DRAFT');
  });

});
