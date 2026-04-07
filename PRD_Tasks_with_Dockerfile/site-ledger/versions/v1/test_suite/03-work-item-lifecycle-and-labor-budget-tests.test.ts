import { getAs, postAs, postWithIfMatch, postRaw, generateIdempotencyKey } from '../../../test-helpers/api-client';
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
  uniqueId,
  unwrap,
} from '../../../test-helpers/resources';
import {
  FX_PROJECT_OPEN_120,
  FX_ELECTRICAL_PERMIT_GRANTED,
  FX_DRAFT_ELECTRICAL_ITEM,
  FX_READY_ELECTRICAL_ITEM,
  FX_INPROGRESS_ELECTRICAL_ITEM,
  FX_READY_GENERAL_ITEM_ZONE_A,
  FX_INPROGRESS_STRUCTURAL_CRITICAL_ZONE_B,
  FX_FAILED_SAFETY_ON_ELECTRICAL,
  FX_ZONE_A_OCCUPIED_BY_ELECTRICAL,
} from '../../../test-helpers/fixtures';

describe('Feature 3: Work Item Lifecycle and Labor Budget Tests', () => {

  test('WORK_001: Creating work item in DRAFT does not reserve labor capacity', async () => {

    const { P } = await FX_ELECTRICAL_PERMIT_GRANTED();

    const res = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'Outlet',
        trade: 'ELECTRICAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 6,
      },
      'FOREMAN',
      generateIdempotencyKey('w1')
    );

    expectSuccess(res);

    const projectRes = await getAs(`/projects/${P}`, 'FOREMAN');
    expectSuccess(projectRes);
    const project = unwrap(projectRes.body);
    expect(project.labor_reserved_hours).toBe(0);
    expect(project.labor_committed_hours).toBe(0);
    expect(project.labor_used_hours).toBe(0);
    expect(project.labor_available_hours).toBe(120);
  });

  test('WORK_002: Creating work item without X-Actor-Role fails with ERR_UNAUTHENTICATED', async () => {

    const { P } = await FX_ELECTRICAL_PERMIT_GRANTED();

    const res = await postRaw(
      `/projects/${P}/work_items`,
      {
        title: 'Outlet',
        trade: 'ELECTRICAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 6,
      },
      { 'Idempotency-Key': generateIdempotencyKey('w2') }
    );

    expectErrorCode(res, 'ERR_UNAUTHENTICATED');

    const projectRes = await getAs(`/projects/${P}`, 'FOREMAN');
    expectSuccess(projectRes);
    const project = unwrap(projectRes.body);
    expect(project.labor_reserved_hours).toBe(0);
    expect(project.labor_committed_hours).toBe(0);
    expect(project.labor_used_hours).toBe(0);
    expect(project.labor_available_hours).toBe(120);
  });

  test('WORK_003: Creating work item with invalid trade MASONRY fails with ERR_BAD_REQUEST', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const res = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'BadTrade',
        trade: 'MASONRY',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 1,
      },
      'FOREMAN',
      generateIdempotencyKey('w3')
    );

    expectErrorCode(res, 'ERR_BAD_REQUEST');

    const projectRes = await getAs(`/projects/${P}`, 'FOREMAN');
    expectSuccess(projectRes);
    const project = unwrap(projectRes.body);
    expect(project.labor_reserved_hours).toBe(0);
    expect(project.labor_committed_hours).toBe(0);
    expect(project.labor_used_hours).toBe(0);
    expect(project.labor_available_hours).toBe(120);
  });

  test('WORK_004: Moving work item from DRAFT to READY reserves labor capacity', async () => {

    const { P, W, EW } = await FX_DRAFT_ELECTRICAL_ITEM();

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/ready`,
      {},
      EW,
      'FOREMAN',
      generateIdempotencyKey('w4')
    );

    expectSuccess(res);

    const workItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemRes);
    expect(unwrap(workItemRes.body).status).toBe('READY');

    const projectRes = await getAs(`/projects/${P}`, 'FOREMAN');
    expectSuccess(projectRes);
    const project = unwrap(projectRes.body);
    expect(project.labor_reserved_hours).toBe(10);
    expect(project.labor_available_hours).toBe(110);
  });

  test('WORK_005: Moving to READY without permit (non-GENERAL trade) fails with ERR_PERMIT_REQUIRED', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const workItemRes = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'NoPermitYet',
        trade: 'ELECTRICAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 5,
      },
      'FOREMAN',
      generateIdempotencyKey('w5')
    );
    expectSuccess(workItemRes);
    const W = unwrap(workItemRes.body).id;

    const getWRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(getWRes);
    const E = unwrap(getWRes.body).etag;

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/ready`,
      {},
      E,
      'FOREMAN',
      generateIdempotencyKey('w5b')
    );

    expectErrorCode(res, 'ERR_PERMIT_REQUIRED');

    const workItemAfterRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemAfterRes);
    expect(unwrap(workItemAfterRes.body).status).toBe('DRAFT');

    const projectRes = await getAs(`/projects/${P}`, 'FOREMAN');
    expectSuccess(projectRes);
    expect(unwrap(projectRes.body).labor_reserved_hours).toBe(0);
  });

  test('WORK_006: GENERAL work does not require permit to move to READY', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const workItemRes = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'GeneralReady',
        trade: 'GENERAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 5,
      },
      'FOREMAN',
      generateIdempotencyKey('w6')
    );
    expectSuccess(workItemRes);
    const W = unwrap(workItemRes.body).id;

    const getWRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(getWRes);
    const E = unwrap(getWRes.body).etag;

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/ready`,
      {},
      E,
      'FOREMAN',
      generateIdempotencyKey('w6b')
    );

    expectSuccess(res);

    const workItemAfterRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemAfterRes);
    expect(unwrap(workItemAfterRes.body).status).toBe('READY');

    const projectRes = await getAs(`/projects/${P}`, 'FOREMAN');
    expectSuccess(projectRes);
    expect(unwrap(projectRes.body).labor_reserved_hours).toBe(5);
  });

  test('WORK_007: Moving to READY without If-Match fails with ERR_MISSING_IF_MATCH', async () => {

    const { P, W } = await FX_DRAFT_ELECTRICAL_ITEM();

    const res = await postAs(
      `/projects/${P}/work_items/${W}/ready`,
      {},
      'FOREMAN',
      generateIdempotencyKey('w7')
    );

    expectErrorCode(res, 'ERR_MISSING_IF_MATCH');

    const workItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemRes);
    expect(unwrap(workItemRes.body).status).toBe('DRAFT');
  });

  test('WORK_008: Moving to READY with stale etag fails with ERR_ETAG_MISMATCH', async () => {

    const { P, W } = await FX_DRAFT_ELECTRICAL_ITEM();

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/ready`,
      {},
      'stale-etag',
      'FOREMAN',
      generateIdempotencyKey('w8')
    );

    expectErrorCode(res, 'ERR_ETAG_MISMATCH');

    const workItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemRes);
    expect(unwrap(workItemRes.body).status).toBe('DRAFT');
  });

  test('WORK_009: Starting work item moves reserved hours to committed hours', async () => {

    const { P, W, EW2 } = await FX_READY_ELECTRICAL_ITEM();

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/start`,
      {},
      EW2,
      'FOREMAN',
      generateIdempotencyKey('w9')
    );

    expectSuccess(res);

    const workItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemRes);
    expect(unwrap(workItemRes.body).status).toBe('IN_PROGRESS');

    const projectRes = await getAs(`/projects/${P}`, 'FOREMAN');
    expectSuccess(projectRes);
    const project = unwrap(projectRes.body);
    expect(project.labor_reserved_hours).toBe(0);
    expect(project.labor_committed_hours).toBe(10);
    expect(project.labor_available_hours).toBe(110);
  });

  test('WORK_010: Starting work item without If-Match fails with ERR_MISSING_IF_MATCH', async () => {

    const { P, W } = await FX_READY_ELECTRICAL_ITEM();

    const res = await postAs(
      `/projects/${P}/work_items/${W}/start`,
      {},
      'FOREMAN',
      generateIdempotencyKey('w10')
    );

    expectErrorCode(res, 'ERR_MISSING_IF_MATCH');

    const workItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemRes);
    expect(unwrap(workItemRes.body).status).toBe('READY');
  });

  test('WORK_011: Starting already IN_PROGRESS work item fails with ERR_INVALID_STATE', async () => {

    const { P, W, EW3 } = await FX_INPROGRESS_ELECTRICAL_ITEM();

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/start`,
      {},
      EW3,
      'FOREMAN',
      generateIdempotencyKey('w11')
    );

    expectErrorCode(res, 'ERR_INVALID_STATE');

    const workItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemRes);
    expect(unwrap(workItemRes.body).status).toBe('IN_PROGRESS');
  });

  test('WORK_012: Completing work item with exact estimated hours', async () => {

    const { P, W, EW3 } = await FX_INPROGRESS_ELECTRICAL_ITEM();

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/complete`,
      { actual_hours: 10 },
      EW3,
      'FOREMAN',
      generateIdempotencyKey('w12')
    );

    expectSuccess(res);

    const workItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemRes);
    expect(unwrap(workItemRes.body).status).toBe('DONE');

    const projectRes = await getAs(`/projects/${P}`, 'FOREMAN');
    expectSuccess(projectRes);
    const project = unwrap(projectRes.body);
    expect(project.labor_committed_hours).toBe(0);
    expect(project.labor_used_hours).toBe(10);
    expect(project.labor_available_hours).toBe(110);
  });

  test('WORK_013: Completing work item with fewer actual hours than estimated', async () => {

    const { P, W, EW3 } = await FX_INPROGRESS_ELECTRICAL_ITEM();

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/complete`,
      { actual_hours: 8 },
      EW3,
      'FOREMAN',
      generateIdempotencyKey('w13')
    );

    expectSuccess(res);

    const workItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemRes);
    expect(unwrap(workItemRes.body).status).toBe('DONE');

    const projectRes = await getAs(`/projects/${P}`, 'FOREMAN');
    expectSuccess(projectRes);
    const project = unwrap(projectRes.body);
    expect(project.labor_used_hours).toBe(8);
    expect(project.labor_available_hours).toBe(112);

    expect(project.labor_committed_hours).toBe(0);
  });

  test('WORK_014: Completing work item with more actual hours than estimated', async () => {

    const { P, W, EW3 } = await FX_INPROGRESS_ELECTRICAL_ITEM();

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/complete`,
      { actual_hours: 12 },
      EW3,
      'FOREMAN',
      generateIdempotencyKey('w14')
    );

    expectSuccess(res);

    const projectRes = await getAs(`/projects/${P}`, 'FOREMAN');
    expectSuccess(projectRes);
    const project = unwrap(projectRes.body);
    expect(project.labor_used_hours).toBe(12);
    expect(project.labor_available_hours).toBe(108);
  });

  test('WORK_015: Completing with actual_hours exceeding budget fails with ERR_LABOR_BUDGET_EXCEEDED', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const workItemRes = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'Huge',
        trade: 'GENERAL',
        zone: 'ZONE_C',
        criticality: 'STANDARD',
        estimated_hours: 120,
      },
      'FOREMAN',
      generateIdempotencyKey('w15')
    );
    expectSuccess(workItemRes);
    const W = unwrap(workItemRes.body).id;

    let getWRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(getWRes);
    let E = unwrap(getWRes.body).etag;

    const readyRes = await postWithIfMatch(`/projects/${P}/work_items/${W}/ready`, {}, E, 'FOREMAN', generateIdempotencyKey('w15b'));
    expectSuccess(readyRes);

    const inspRes = await postAs(
      `/projects/${P}/inspections`,
      { work_item_id: W, kind: 'SAFETY' },
      'INSPECTOR',
      generateIdempotencyKey('w15s1')
    );
    expectSuccess(inspRes);
    const IS = unwrap(inspRes.body).id;

    const submitRes = await postAs(
      `/projects/${P}/inspections/${IS}/submit`,
      { outcome: 'PASSED' },
      'INSPECTOR',
      generateIdempotencyKey('w15s2')
    );
    expectSuccess(submitRes);

    getWRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(getWRes);
    E = unwrap(getWRes.body).etag;

    const startRes = await postWithIfMatch(`/projects/${P}/work_items/${W}/start`, {}, E, 'FOREMAN', generateIdempotencyKey('w15c'));
    expectSuccess(startRes);

    getWRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(getWRes);
    const E3 = unwrap(getWRes.body).etag;

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/complete`,
      { actual_hours: 121 },
      E3,
      'FOREMAN',
      generateIdempotencyKey('w15d')
    );

    expectErrorCode(res, 'ERR_LABOR_BUDGET_EXCEEDED');

    const workItemAfterRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemAfterRes);
    expect(unwrap(workItemAfterRes.body).status).toBe('IN_PROGRESS');

    const projectRes = await getAs(`/projects/${P}`, 'FOREMAN');
    expectSuccess(projectRes);
    const project = unwrap(projectRes.body);
    expect(project.labor_used_hours).toBe(0);
    expect(project.labor_committed_hours).toBe(120);
    expect(project.labor_available_hours).toBe(0);
  });

  test('WORK_016: Reserving labor that would exceed budget fails with ERR_LABOR_BUDGET_EXCEEDED', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const workItemRes = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'ReserveTooMuch',
        trade: 'GENERAL',
        zone: 'ZONE_C',
        criticality: 'STANDARD',
        estimated_hours: 121,
      },
      'FOREMAN',
      generateIdempotencyKey('w16')
    );
    expectSuccess(workItemRes);
    const W = unwrap(workItemRes.body).id;

    const getWRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(getWRes);
    const E = unwrap(getWRes.body).etag;

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/ready`,
      {},
      E,
      'FOREMAN',
      generateIdempotencyKey('w16b')
    );

    expectErrorCode(res, 'ERR_LABOR_BUDGET_EXCEEDED');

    const workItemAfterRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemAfterRes);
    expect(unwrap(workItemAfterRes.body).status).toBe('DRAFT');

    const projectRes = await getAs(`/projects/${P}`, 'FOREMAN');
    expectSuccess(projectRes);
    const project = unwrap(projectRes.body);
    expect(project.labor_reserved_hours).toBe(0);
    expect(project.labor_available_hours).toBe(120);
  });

  test('WORK_017: Cancelling READY work item releases reserved hours', async () => {

    const { P, W, EW2 } = await FX_READY_ELECTRICAL_ITEM();

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/cancel`,
      {},
      EW2,
      'FOREMAN',
      generateIdempotencyKey('w17')
    );

    expectSuccess(res);

    const workItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemRes);
    expect(unwrap(workItemRes.body).status).toBe('CANCELLED');

    const projectRes = await getAs(`/projects/${P}`, 'FOREMAN');
    expectSuccess(projectRes);
    const project = unwrap(projectRes.body);
    expect(project.labor_reserved_hours).toBe(0);
    expect(project.labor_available_hours).toBe(120);
  });

  test('WORK_018: Cancelling IN_PROGRESS work item releases committed hours', async () => {

    const { P, W, EW3 } = await FX_INPROGRESS_ELECTRICAL_ITEM();

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/cancel`,
      {},
      EW3,
      'FOREMAN',
      generateIdempotencyKey('w18')
    );

    expectSuccess(res);

    const workItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemRes);
    expect(unwrap(workItemRes.body).status).toBe('CANCELLED');

    const projectRes = await getAs(`/projects/${P}`, 'FOREMAN');
    expectSuccess(projectRes);
    const project = unwrap(projectRes.body);
    expect(project.labor_committed_hours).toBe(0);
    expect(project.labor_available_hours).toBe(120);
  });

  test('WORK_019: Starting a CANCELLED work item fails with ERR_INVALID_STATE', async () => {

    const { P, W, EW3 } = await FX_INPROGRESS_ELECTRICAL_ITEM();

    await postWithIfMatch(
      `/projects/${P}/work_items/${W}/cancel`,
      {},
      EW3,
      'FOREMAN',
      generateIdempotencyKey('w19')
    );

    const getWRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(getWRes);
    const currentEtag = unwrap(getWRes.body).etag;

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/start`,
      {},
      currentEtag,
      'FOREMAN',
      generateIdempotencyKey('w19b')
    );

    expectErrorCode(res, 'ERR_INVALID_STATE');

    const workItemAfterRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemAfterRes);
    expect(unwrap(workItemAfterRes.body).status).toBe('CANCELLED');
  });

  test('WORK_020: Cancelling a DONE work item fails with ERR_INVALID_STATE', async () => {

    const { P, W, EW3 } = await FX_INPROGRESS_ELECTRICAL_ITEM();

    await postWithIfMatch(
      `/projects/${P}/work_items/${W}/complete`,
      { actual_hours: 10 },
      EW3,
      'FOREMAN',
      generateIdempotencyKey('w20')
    );

    const getWRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(getWRes);
    const currentEtag = unwrap(getWRes.body).etag;

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/cancel`,
      {},
      currentEtag,
      'FOREMAN',
      generateIdempotencyKey('w20b')
    );

    expectErrorCode(res, 'ERR_INVALID_STATE');

    const workItemAfterRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemAfterRes);
    expect(unwrap(workItemAfterRes.body).status).toBe('DONE');
  });

  test('WORK_021: Completing work item blocked by FAILED quality inspection', async () => {

    const { P, W, EW3 } = await FX_INPROGRESS_ELECTRICAL_ITEM();

    const inspectionRes = await postAs(
      `/projects/${P}/inspections`,
      { work_item_id: W, kind: 'QUALITY' },
      'INSPECTOR',
      generateIdempotencyKey('w21')
    );
    expectSuccess(inspectionRes);
    const IQ = unwrap(inspectionRes.body).id;

    await postAs(
      `/projects/${P}/inspections/${IQ}/submit`,
      { outcome: 'FAILED' },
      'INSPECTOR',
      generateIdempotencyKey('w21b')
    );

    const refreshRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(refreshRes);
    const freshEtag = unwrap(refreshRes.body).etag;

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/complete`,
      { actual_hours: 10 },
      freshEtag,
      'FOREMAN',
      generateIdempotencyKey('w21c')
    );

    expectErrorCode(res, 'ERR_QUALITY_FAILED_BLOCKING');

    const workItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemRes);
    expect(unwrap(workItemRes.body).status).toBe('IN_PROGRESS');
  });

  test('WORK_022: CRITICAL work item without quality inspection fails to complete', async () => {

    const { P, WS, EWS3 } = await FX_INPROGRESS_STRUCTURAL_CRITICAL_ZONE_B();

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${WS}/complete`,
      { actual_hours: 30 },
      EWS3,
      'FOREMAN',
      generateIdempotencyKey('w22')
    );

    expectErrorCode(res, 'ERR_QUALITY_FAILED_BLOCKING');

    const workItemRes = await getAs(`/projects/${P}/work_items/${WS}`, 'FOREMAN');
    expectSuccess(workItemRes);
    expect(unwrap(workItemRes.body).status).toBe('IN_PROGRESS');
  });

  test('WORK_023: CRITICAL work item with PASSED quality inspection can complete', async () => {

    const { P, WS, EWS3 } = await FX_INPROGRESS_STRUCTURAL_CRITICAL_ZONE_B();

    const inspectionRes = await postAs(
      `/projects/${P}/inspections`,
      { work_item_id: WS, kind: 'QUALITY' },
      'INSPECTOR',
      generateIdempotencyKey('w23')
    );
    expectSuccess(inspectionRes);
    const IQ = unwrap(inspectionRes.body).id;

    await postAs(
      `/projects/${P}/inspections/${IQ}/submit`,
      { outcome: 'PASSED' },
      'INSPECTOR',
      generateIdempotencyKey('w23b')
    );

    const refreshRes = await getAs(`/projects/${P}/work_items/${WS}`, 'FOREMAN');
    expectSuccess(refreshRes);
    const freshEtag = unwrap(refreshRes.body).etag;

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${WS}/complete`,
      { actual_hours: 30 },
      freshEtag,
      'FOREMAN',
      generateIdempotencyKey('w23c')
    );

    expectSuccess(res);

    const workItemRes = await getAs(`/projects/${P}/work_items/${WS}`, 'FOREMAN');
    expectSuccess(workItemRes);
    expect(unwrap(workItemRes.body).status).toBe('DONE');
  });

  test('WORK_024: Work item with is_startable=true and empty start_blockers can start', async () => {

    const { P, W, EW2 } = await FX_READY_ELECTRICAL_ITEM();

    const getWRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(getWRes);
    const workItem = unwrap(getWRes.body);
    expect(workItem.is_startable).toBe(true);
    expect(workItem.start_blockers).toEqual([]);

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/start`,
      {},
      EW2,
      'FOREMAN',
      generateIdempotencyKey('w24')
    );

    expectSuccess(res);

    const workItemAfterRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemAfterRes);
    expect(unwrap(workItemAfterRes.body).status).toBe('IN_PROGRESS');
  });

  test('WORK_025: Approved change order freezes work item (CHANGE_ORDER blocker)', async () => {

    const { P, W, EW2 } = await FX_READY_ELECTRICAL_ITEM();

    const coRes = await postAs(
      `/projects/${P}/change_orders`,
      { work_item_id: W, summary: 'Hold', labor_budget_hours_delta: 1 },
      'FOREMAN',
      generateIdempotencyKey('w25')
    );
    expectSuccess(coRes);
    const CO = unwrap(coRes.body).id;

    const getCoRes = await getAs(`/projects/${P}/change_orders/${CO}`, 'FOREMAN');
    expectSuccess(getCoRes);
    const ECO = unwrap(getCoRes.body).etag;

    await postWithIfMatch(
      `/projects/${P}/change_orders/${CO}/approve`,
      {},
      ECO,
      'MANAGER',
      generateIdempotencyKey('w25b')
    );

    const res = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');

    expectSuccess(res);
    const workItem = unwrap(res.body);
    expect(workItem.is_startable).toBe(false);
    expect(workItem.start_blockers).toContain('CHANGE_ORDER');
  });

  test('WORK_026: Failed safety inspection adds POSTURE blocker', async () => {

    const { P, W, EW2 } = await FX_READY_ELECTRICAL_ITEM();

    const inspectionRes = await postAs(
      `/projects/${P}/inspections`,
      { work_item_id: W, kind: 'SAFETY' },
      'INSPECTOR',
      generateIdempotencyKey('w26')
    );
    expectSuccess(inspectionRes);
    const IS = unwrap(inspectionRes.body).id;

    await postAs(
      `/projects/${P}/inspections/${IS}/submit`,
      { outcome: 'FAILED' },
      'INSPECTOR',
      generateIdempotencyKey('w26b')
    );

    const res = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');

    expectSuccess(res);
    const workItem = unwrap(res.body);
    expect(workItem.is_startable).toBe(false);
    expect(workItem.start_blockers).toContain('POSTURE');
  });

  test('WORK_027: Starting a DRAFT work item fails with ERR_INVALID_STATE', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const workItemRes = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'Z',
        trade: 'GENERAL',
        zone: 'ZONE_C',
        criticality: 'STANDARD',
        estimated_hours: 10,
      },
      'FOREMAN',
      generateIdempotencyKey('w27')
    );
    expectSuccess(workItemRes);
    const W = unwrap(workItemRes.body).id;

    const getWRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(getWRes);
    const E = unwrap(getWRes.body).etag;

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/start`,
      {},
      E,
      'FOREMAN',
      generateIdempotencyKey('w27b')
    );

    expectErrorCode(res, 'ERR_INVALID_STATE');

    const workItemAfterRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemAfterRes);
    expect(unwrap(workItemAfterRes.body).status).toBe('DRAFT');
  });

  test('WORK_028: READY GENERAL work item is startable (no zone/permit blockers)', async () => {

    const { P, WG } = await FX_READY_GENERAL_ITEM_ZONE_A();

    const res = await getAs(`/projects/${P}/work_items/${WG}`, 'FOREMAN');

    expectSuccess(res);
    const workItem = unwrap(res.body);
    expect(workItem.is_startable).toBe(true);
    expect(workItem.start_blockers).toEqual([]);
  });

  test('WORK_029: Reserving 100 hours leaves 20 available (boundary, still OPEN)', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const workItemRes = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'Boundary',
        trade: 'GENERAL',
        zone: 'ZONE_C',
        criticality: 'STANDARD',
        estimated_hours: 100,
      },
      'FOREMAN',
      generateIdempotencyKey('w29')
    );
    expectSuccess(workItemRes);
    const W = unwrap(workItemRes.body).id;

    let getWRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(getWRes);
    const E = unwrap(getWRes.body).etag;

    await postWithIfMatch(`/projects/${P}/work_items/${W}/ready`, {}, E, 'FOREMAN', generateIdempotencyKey('w29b'));

    getWRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(getWRes);

    const res = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');

    expectSuccess(res);
    const workItem = unwrap(res.body);
    expect(workItem.is_startable).toBe(true);
    expect(workItem.start_blockers).toEqual([]);
  });

  test('WORK_030: Reserving 102 hours leaves 18 available (triggers REVIEW, SAFETY blocker)', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const workItemRes = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'ReviewTrigger',
        trade: 'GENERAL',
        zone: 'ZONE_C',
        criticality: 'STANDARD',
        estimated_hours: 102,
      },
      'FOREMAN',
      generateIdempotencyKey('w30')
    );
    expectSuccess(workItemRes);
    const W = unwrap(workItemRes.body).id;

    let getWRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(getWRes);
    const E = unwrap(getWRes.body).etag;

    await postWithIfMatch(`/projects/${P}/work_items/${W}/ready`, {}, E, 'FOREMAN', generateIdempotencyKey('w30b'));

    const projectRes = await getAs(`/projects/${P}`, 'FOREMAN');
    expectSuccess(projectRes);
    expect(unwrap(projectRes.body).posture).toBe('REVIEW');

    const res = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');

    expectSuccess(res);
    const workItem = unwrap(res.body);
    expect(workItem.is_startable).toBe(false);
    expect(workItem.start_blockers).toContain('SAFETY');
  });

  test('WORK_031: In REVIEW posture, work item with PASSED safety can start', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const workItemRes = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'ReviewStart',
        trade: 'GENERAL',
        zone: 'ZONE_C',
        criticality: 'STANDARD',
        estimated_hours: 102,
      },
      'FOREMAN',
      generateIdempotencyKey('w31')
    );
    expectSuccess(workItemRes);
    const W = unwrap(workItemRes.body).id;

    let getWRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(getWRes);
    let E = unwrap(getWRes.body).etag;

    await postWithIfMatch(`/projects/${P}/work_items/${W}/ready`, {}, E, 'FOREMAN', generateIdempotencyKey('w31b'));

    const inspectionRes = await postAs(
      `/projects/${P}/inspections`,
      { work_item_id: W, kind: 'SAFETY' },
      'INSPECTOR',
      generateIdempotencyKey('w31c')
    );
    expectSuccess(inspectionRes);
    const IS = unwrap(inspectionRes.body).id;

    await postAs(
      `/projects/${P}/inspections/${IS}/submit`,
      { outcome: 'PASSED' },
      'INSPECTOR',
      generateIdempotencyKey('w31d')
    );

    getWRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(getWRes);
    const E2 = unwrap(getWRes.body).etag;

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/start`,
      {},
      E2,
      'FOREMAN',
      generateIdempotencyKey('w31e')
    );

    expectSuccess(res);

    const workItemAfterRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemAfterRes);
    expect(unwrap(workItemAfterRes.body).status).toBe('IN_PROGRESS');
  });

  test('WORK_032: Completing work item in STOP_WORK fails with ERR_POSTURE_BLOCKED', async () => {

    const { P, W, EW3 } = await FX_FAILED_SAFETY_ON_ELECTRICAL();

    const getWRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(getWRes);
    const currentEtag = unwrap(getWRes.body).etag;

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/complete`,
      { actual_hours: 10 },
      currentEtag,
      'FOREMAN',
      generateIdempotencyKey('w32')
    );

    expectErrorCode(res, 'ERR_POSTURE_BLOCKED');

    const workItemAfterRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemAfterRes);
    expect(unwrap(workItemAfterRes.body).status).toBe('IN_PROGRESS');
  });

  test('WORK_033: Cancelling work item in STOP_WORK succeeds and restores posture', async () => {

    const { P, W } = await FX_FAILED_SAFETY_ON_ELECTRICAL();

    const getWRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(getWRes);
    const currentEtag = unwrap(getWRes.body).etag;

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/cancel`,
      {},
      currentEtag,
      'FOREMAN',
      generateIdempotencyKey('w33')
    );

    expectSuccess(res);

    const workItemAfterRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemAfterRes);
    expect(unwrap(workItemAfterRes.body).status).toBe('CANCELLED');

    const projectRes = await getAs(`/projects/${P}`, 'FOREMAN');
    expectSuccess(projectRes);
    expect(unwrap(projectRes.body).posture).toBe('OPEN');
  });

  test('WORK_034: Multiple work items can reserve full labor budget', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const w1Res = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'A1',
        trade: 'GENERAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 60,
      },
      'FOREMAN',
      generateIdempotencyKey('w34')
    );
    expectSuccess(w1Res);
    const W1 = unwrap(w1Res.body).id;

    let getW1Res = await getAs(`/projects/${P}/work_items/${W1}`, 'FOREMAN');
    expectSuccess(getW1Res);
    const E1 = unwrap(getW1Res.body).etag;

    await postWithIfMatch(`/projects/${P}/work_items/${W1}/ready`, {}, E1, 'FOREMAN', generateIdempotencyKey('w34b'));

    const w2Res = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'A2',
        trade: 'GENERAL',
        zone: 'ZONE_B',
        criticality: 'STANDARD',
        estimated_hours: 60,
      },
      'FOREMAN',
      generateIdempotencyKey('w34c')
    );
    expectSuccess(w2Res);
    const W2 = unwrap(w2Res.body).id;

    const getW2Res = await getAs(`/projects/${P}/work_items/${W2}`, 'FOREMAN');
    expectSuccess(getW2Res);
    const E2 = unwrap(getW2Res.body).etag;

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W2}/ready`,
      {},
      E2,
      'FOREMAN',
      generateIdempotencyKey('w34d')
    );

    expectSuccess(res);

    const projectRes = await getAs(`/projects/${P}`, 'FOREMAN');
    expectSuccess(projectRes);
    const project = unwrap(projectRes.body);
    expect(project.labor_reserved_hours).toBe(120);
    expect(project.labor_available_hours).toBe(0);
  });

  test('WORK_035: Second work item exceeding budget fails with ERR_LABOR_BUDGET_EXCEEDED', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const w1Res = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'B1',
        trade: 'GENERAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 60,
      },
      'FOREMAN',
      generateIdempotencyKey('w35')
    );
    expectSuccess(w1Res);
    const W1 = unwrap(w1Res.body).id;

    let getW1Res = await getAs(`/projects/${P}/work_items/${W1}`, 'FOREMAN');
    expectSuccess(getW1Res);
    const E1 = unwrap(getW1Res.body).etag;

    await postWithIfMatch(`/projects/${P}/work_items/${W1}/ready`, {}, E1, 'FOREMAN', generateIdempotencyKey('w35b'));

    const w2Res = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'B2',
        trade: 'GENERAL',
        zone: 'ZONE_B',
        criticality: 'STANDARD',
        estimated_hours: 61,
      },
      'FOREMAN',
      generateIdempotencyKey('w35c')
    );
    expectSuccess(w2Res);
    const W2 = unwrap(w2Res.body).id;

    const getW2Res = await getAs(`/projects/${P}/work_items/${W2}`, 'FOREMAN');
    expectSuccess(getW2Res);
    const E2 = unwrap(getW2Res.body).etag;

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W2}/ready`,
      {},
      E2,
      'FOREMAN',
      generateIdempotencyKey('w35d')
    );

    expectErrorCode(res, 'ERR_LABOR_BUDGET_EXCEEDED');

    const projectRes = await getAs(`/projects/${P}`, 'FOREMAN');
    expectSuccess(projectRes);
    const project = unwrap(projectRes.body);
    expect(project.labor_reserved_hours).toBe(60);
    expect(project.labor_available_hours).toBe(60);

    const w2AfterRes = await getAs(`/projects/${P}/work_items/${W2}`, 'FOREMAN');
    expectSuccess(w2AfterRes);
    expect(unwrap(w2AfterRes.body).status).toBe('DRAFT');
  });

  test('WORK_036: Revoking permit blocks starting with POSTURE blocker', async () => {

    const { P, PE, W } = await FX_READY_ELECTRICAL_ITEM();

    await postAs(
      `/projects/${P}/permits/${PE}/decide`,
      { decision: 'REVOKE' },
      'MANAGER',
      generateIdempotencyKey('w36')
    );

    const res = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');

    expectSuccess(res);
    const workItem = unwrap(res.body);
    expect(workItem.is_startable).toBe(false);
    expect(workItem.start_blockers).toContain('POSTURE');
  });

  test('WORK_037: Zone occupied by non-GENERAL work item blocks other non-GENERAL starts', async () => {

    const { P } = await FX_ELECTRICAL_PERMIT_GRANTED();

    const w1Res = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'ZoneA',
        trade: 'ELECTRICAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 5,
      },
      'FOREMAN',
      generateIdempotencyKey('w37')
    );
    expectSuccess(w1Res);
    const W1 = unwrap(w1Res.body).id;

    let getW1Res = await getAs(`/projects/${P}/work_items/${W1}`, 'FOREMAN');
    expectSuccess(getW1Res);
    let E1 = unwrap(getW1Res.body).etag;

    await postWithIfMatch(`/projects/${P}/work_items/${W1}/ready`, {}, E1, 'FOREMAN', generateIdempotencyKey('w37b'));

    getW1Res = await getAs(`/projects/${P}/work_items/${W1}`, 'FOREMAN');
    expectSuccess(getW1Res);
    E1 = unwrap(getW1Res.body).etag;

    await postWithIfMatch(`/projects/${P}/work_items/${W1}/start`, {}, E1, 'FOREMAN', generateIdempotencyKey('w37c'));

    const w2Res = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'ZoneA2',
        trade: 'ELECTRICAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 5,
      },
      'FOREMAN',
      generateIdempotencyKey('w37d')
    );
    expectSuccess(w2Res);
    const W2 = unwrap(w2Res.body).id;

    let getW2Res = await getAs(`/projects/${P}/work_items/${W2}`, 'FOREMAN');
    expectSuccess(getW2Res);
    let E2 = unwrap(getW2Res.body).etag;

    await postWithIfMatch(`/projects/${P}/work_items/${W2}/ready`, {}, E2, 'FOREMAN', generateIdempotencyKey('w37e'));

    getW2Res = await getAs(`/projects/${P}/work_items/${W2}`, 'FOREMAN');
    expectSuccess(getW2Res);
    const E2b = unwrap(getW2Res.body).etag;

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W2}/start`,
      {},
      E2b,
      'FOREMAN',
      generateIdempotencyKey('w37f')
    );

    expectErrorCode(res, 'ERR_ZONE_OCCUPIED');

    const w2AfterRes = await getAs(`/projects/${P}/work_items/${W2}`, 'FOREMAN');
    expectSuccess(w2AfterRes);
    expect(unwrap(w2AfterRes.body).status).toBe('READY');
  });

  test('WORK_038: GENERAL work can start in zone occupied by non-GENERAL work', async () => {

    const { P } = await FX_ZONE_A_OCCUPIED_BY_ELECTRICAL();

    const w2Res = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'GeneralWhileBusy',
        trade: 'GENERAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 2,
      },
      'FOREMAN',
      generateIdempotencyKey('w38')
    );
    expectSuccess(w2Res);
    const W2 = unwrap(w2Res.body).id;

    let getW2Res = await getAs(`/projects/${P}/work_items/${W2}`, 'FOREMAN');
    expectSuccess(getW2Res);
    let E2 = unwrap(getW2Res.body).etag;

    await postWithIfMatch(`/projects/${P}/work_items/${W2}/ready`, {}, E2, 'FOREMAN', generateIdempotencyKey('w38b'));

    getW2Res = await getAs(`/projects/${P}/work_items/${W2}`, 'FOREMAN');
    expectSuccess(getW2Res);
    const E2b = unwrap(getW2Res.body).etag;

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W2}/start`,
      {},
      E2b,
      'FOREMAN',
      generateIdempotencyKey('w38c')
    );

    expectSuccess(res);

    const w2AfterRes = await getAs(`/projects/${P}/work_items/${W2}`, 'FOREMAN');
    expectSuccess(w2AfterRes);
    expect(unwrap(w2AfterRes.body).status).toBe('IN_PROGRESS');
  });

});
