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
  uniqueId,
  unwrap,
} from '../../../test-helpers/resources';
import {
  FX_PROJECT_OPEN_120,
  FX_PROJECT_REVIEW_18,
  FX_ELECTRICAL_PERMIT_GRANTED,
  FX_READY_ELECTRICAL_ITEM,
  FX_INPROGRESS_ELECTRICAL_ITEM,
  FX_FAILED_SAFETY_ON_ELECTRICAL,
  FX_TWO_ACTIVE_QUALITY_FAILS,
} from '../../../test-helpers/fixtures';

describe('Feature 1: Project and Posture Tests', () => {

  test('PROJECT_001: GET project with posture=OPEN and initial labor accounting', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const res = await getAs(`/projects/${P}`, 'FOREMAN');

    expectSuccess(res);
    const project = unwrap(res.body);
    expect(project.posture).toBe('OPEN');
    expect(project.labor_budget_hours).toBe(120);
    expect(project.labor_reserved_hours).toBe(0);
    expect(project.labor_committed_hours).toBe(0);
    expect(project.labor_used_hours).toBe(0);
    expect(project.labor_available_hours).toBe(120);
  });

  test('PROJECT_002: GET project with posture=REVIEW due to labor_available_hours < 20', async () => {

    const { P } = await FX_PROJECT_REVIEW_18();

    const res = await getAs(`/projects/${P}`, 'INSPECTOR');

    expectSuccess(res);
    const project = unwrap(res.body);
    expect(project.posture).toBe('REVIEW');
    expect(project.labor_available_hours).toBe(18);
  });

  test('PROJECT_003: GET project with granted ELECTRICAL permit shows posture=OPEN', async () => {

    const { P, PE } = await FX_ELECTRICAL_PERMIT_GRANTED();

    const res = await getAs(`/projects/${P}`, 'MANAGER');

    expectSuccess(res);
    const project = unwrap(res.body);
    expect(project.posture).toBe('OPEN');

    const electricalPermit = project.permits.find((p: any) => p.trade === 'ELECTRICAL');
    expect(electricalPermit).toBeDefined();
    expect(electricalPermit.status).toBe('GRANTED');
  });

  test('PROJECT_004: Revoking a permit with no active READY/IN_PROGRESS work keeps posture OPEN', async () => {

    const { P, PE } = await FX_ELECTRICAL_PERMIT_GRANTED();

    const revokeRes = await postAs(
      `/projects/${P}/permits/${PE}/decide`,
      { decision: 'REVOKE' },
      'MANAGER',
      generateIdempotencyKey('pr4')
    );
    expectSuccess(revokeRes);

    const res = await getAs(`/projects/${P}`, 'FOREMAN');

    expectSuccess(res);
    const project = unwrap(res.body);
    expect(project.posture).toBe('OPEN');

    const electricalPermit = project.permits.find((p: any) => p.trade === 'ELECTRICAL');
    expect(electricalPermit).toBeDefined();
    expect(electricalPermit.status).toBe('REVOKED');
  });

  test('PROJECT_005: Revoking permit with READY work item causes STOP_WORK', async () => {

    const { P, PE } = await FX_READY_ELECTRICAL_ITEM();

    const confirmRes = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(confirmRes);
    expect(unwrap(confirmRes.body).posture).toBe('OPEN');

    await postAs(
      `/projects/${P}/permits/${PE}/decide`,
      { decision: 'REVOKE' },
      'MANAGER',
      generateIdempotencyKey('pr5')
    );

    const res = await getAs(`/projects/${P}`, 'MANAGER');

    expectSuccess(res);
    const project = unwrap(res.body);
    expect(project.posture).toBe('STOP_WORK');

    const electricalPermit = project.permits.find((p: any) => p.trade === 'ELECTRICAL');
    expect(electricalPermit).toBeDefined();
    expect(electricalPermit.status).toBe('REVOKED');
  });

  test('PROJECT_006: Failed safety inspection causes STOP_WORK', async () => {

    const { P } = await FX_FAILED_SAFETY_ON_ELECTRICAL();

    const res = await getAs(`/projects/${P}`, 'INSPECTOR');

    expectSuccess(res);
    const project = unwrap(res.body);
    expect(project.posture).toBe('STOP_WORK');
  });

  test('PROJECT_007: Passing safety inspection after failure returns posture to OPEN', async () => {

    const { P, W } = await FX_FAILED_SAFETY_ON_ELECTRICAL();

    const inspRes = await postAs(
      `/projects/${P}/inspections`,
      { work_item_id: W, kind: 'SAFETY' },
      'INSPECTOR',
      generateIdempotencyKey('pr7')
    );
    expectSuccess(inspRes);
    const IS2 = unwrap(inspRes.body).id;

    await postAs(
      `/projects/${P}/inspections/${IS2}/submit`,
      { outcome: 'PASSED' },
      'INSPECTOR',
      generateIdempotencyKey('pr7b')
    );

    const res = await getAs(`/projects/${P}`, 'MANAGER');

    expectSuccess(res);
    const project = unwrap(res.body);
    expect(project.posture).toBe('OPEN');
  });

  test('PROJECT_008: Two active work items with quality failures cause REVIEW', async () => {

    const { P } = await FX_TWO_ACTIVE_QUALITY_FAILS();

    const res = await getAs(`/projects/${P}`, 'FOREMAN');

    expectSuccess(res);
    const project = unwrap(res.body);
    expect(project.posture).toBe('REVIEW');
  });

  test('PROJECT_009: Cancelling one of two quality-failed items returns posture to OPEN', async () => {

    const { P, W1 } = await FX_TWO_ACTIVE_QUALITY_FAILS();

    const beforeRes = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(beforeRes);
    expect(unwrap(beforeRes.body).posture).toBe('REVIEW');

    const workItemRes = await getAs(`/projects/${P}/work_items/${W1}`, 'FOREMAN');
    expectSuccess(workItemRes);
    const etag = unwrap(workItemRes.body).etag;

    const cancelRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W1}/cancel`,
      {},
      etag,
      'FOREMAN',
      generateIdempotencyKey('pr9')
    );
    expectSuccess(cancelRes);

    const w1AfterRes = await getAs(`/projects/${P}/work_items/${W1}`, 'FOREMAN');
    expectSuccess(w1AfterRes);
    expect(unwrap(w1AfterRes.body).status).toBe('CANCELLED');

    const res = await getAs(`/projects/${P}`, 'MANAGER');

    expectSuccess(res);
    const project = unwrap(res.body);
    expect(project.posture).toBe('OPEN');
  });

  test('PROJECT_010: Work item moved to READY causes labor_reserved_hours update and posture=REVIEW when under 20 available', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const createRes = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'Big',
        trade: 'GENERAL',
        zone: 'ZONE_C',
        criticality: 'STANDARD',
        estimated_hours: 105,
      },
      'FOREMAN',
      generateIdempotencyKey('pr10')
    );
    expectSuccess(createRes);
    const W = unwrap(createRes.body).id;

    const getRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(getRes);
    const EW = unwrap(getRes.body).etag;

    await postWithIfMatch(
      `/projects/${P}/work_items/${W}/ready`,
      {},
      EW,
      'FOREMAN',
      generateIdempotencyKey('pr10b')
    );

    const res = await getAs(`/projects/${P}`, 'FOREMAN');

    expectSuccess(res);
    const project = unwrap(res.body);
    expect(project.posture).toBe('REVIEW');
    expect(project.labor_reserved_hours).toBe(105);
    expect(project.labor_available_hours).toBe(15);
  });

  test('PROJECT_011: Posture becomes REVIEW when labor_available_hours is 19 (under 20)', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const createRes = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'Almost',
        trade: 'GENERAL',
        zone: 'ZONE_C',
        criticality: 'STANDARD',
        estimated_hours: 101,
      },
      'FOREMAN',
      generateIdempotencyKey('pr11')
    );
    expectSuccess(createRes);
    const W = unwrap(createRes.body).id;

    const getRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(getRes);
    const EW = unwrap(getRes.body).etag;

    await postWithIfMatch(
      `/projects/${P}/work_items/${W}/ready`,
      {},
      EW,
      'FOREMAN',
      generateIdempotencyKey('pr11b')
    );

    const res = await getAs(`/projects/${P}`, 'FOREMAN');

    expectSuccess(res);
    const project = unwrap(res.body);
    expect(project.posture).toBe('REVIEW');
    expect(project.labor_available_hours).toBe(19);
  });

  test('PROJECT_012: Posture becomes REVIEW when labor_available_hours drops to 18 (under 20)', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const createRes = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'Tight',
        trade: 'GENERAL',
        zone: 'ZONE_C',
        criticality: 'STANDARD',
        estimated_hours: 102,
      },
      'FOREMAN',
      generateIdempotencyKey('pr12')
    );
    expectSuccess(createRes);
    const W = unwrap(createRes.body).id;

    const getRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(getRes);
    const EW = unwrap(getRes.body).etag;

    await postWithIfMatch(
      `/projects/${P}/work_items/${W}/ready`,
      {},
      EW,
      'FOREMAN',
      generateIdempotencyKey('pr12b')
    );

    const res = await getAs(`/projects/${P}`, 'FOREMAN');

    expectSuccess(res);
    const project = unwrap(res.body);
    expect(project.posture).toBe('REVIEW');
    expect(project.labor_available_hours).toBe(18);
  });

  test('PROJECT_013: Safety failure overrides quality failure for STOP_WORK posture', async () => {

    const { P, W } = await FX_INPROGRESS_ELECTRICAL_ITEM();

    const safetyRes = await postAs(
      `/projects/${P}/inspections`,
      { work_item_id: W, kind: 'SAFETY' },
      'INSPECTOR',
      generateIdempotencyKey('pr13')
    );
    expectSuccess(safetyRes);
    const IS = unwrap(safetyRes.body).id;

    await postAs(
      `/projects/${P}/inspections/${IS}/submit`,
      { outcome: 'FAILED' },
      'INSPECTOR',
      generateIdempotencyKey('pr13b')
    );

    const qualityRes = await postAs(
      `/projects/${P}/inspections`,
      { work_item_id: W, kind: 'QUALITY' },
      'INSPECTOR',
      generateIdempotencyKey('pr13c')
    );
    expectSuccess(qualityRes);
    const IQ = unwrap(qualityRes.body).id;

    await postAs(
      `/projects/${P}/inspections/${IQ}/submit`,
      { outcome: 'FAILED' },
      'INSPECTOR',
      generateIdempotencyKey('pr13d')
    );

    const res = await getAs(`/projects/${P}`, 'MANAGER');

    expectSuccess(res);
    const project = unwrap(res.body);
    expect(project.posture).toBe('STOP_WORK');
  });

  test('PROJECT_014: Creating DRAFT work item with revoked permit keeps posture OPEN (no STOP_WORK without READY/IN_PROGRESS)', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const permitRes = await postAs(
      `/projects/${P}/permits`,
      { trade: 'ELECTRICAL' },
      'MANAGER',
      generateIdempotencyKey('pr14')
    );
    expectSuccess(permitRes);
    const PE = unwrap(permitRes.body).id;

    await postAs(
      `/projects/${P}/permits/${PE}/decide`,
      { decision: 'REVOKE' },
      'MANAGER',
      generateIdempotencyKey('pr14b')
    );

    const createRes = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'Panel2',
        trade: 'ELECTRICAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 5,
      },
      'FOREMAN',
      generateIdempotencyKey('pr14c')
    );

    expectSuccess(createRes);
    const workItem = unwrap(createRes.body);
    expect(workItem.status).toBe('DRAFT');

    const projectRes = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(projectRes);
    const project = unwrap(projectRes.body);
    expect(project.posture).toBe('OPEN');
  });

  test('PROJECT_015: Completing a work item returns posture to OPEN', async () => {

    const { P, W, EW3 } = await FX_INPROGRESS_ELECTRICAL_ITEM();

    const completeRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/complete`,
      { actual_hours: 10 },
      EW3,
      'FOREMAN',
      generateIdempotencyKey('pr15')
    );
    expectSuccess(completeRes);

    const workItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemRes);
    expect(unwrap(workItemRes.body).status).toBe('DONE');

    const projectConfirmRes = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(projectConfirmRes);
    expect(unwrap(projectConfirmRes.body).posture).toBe('OPEN');

    const res = await getAs(`/projects/${P}`, 'MANAGER');

    expectSuccess(res);
    const project = unwrap(res.body);
    expect(project.posture).toBe('OPEN');
  });

  test('PROJECT_016: Cancelling work item with failed safety returns posture to OPEN', async () => {

    const { P, W } = await FX_INPROGRESS_ELECTRICAL_ITEM();

    const inspRes = await postAs(
      `/projects/${P}/inspections`,
      { work_item_id: W, kind: 'SAFETY' },
      'INSPECTOR',
      generateIdempotencyKey('pr16')
    );
    expectSuccess(inspRes);
    const IS = unwrap(inspRes.body).id;

    await postAs(
      `/projects/${P}/inspections/${IS}/submit`,
      { outcome: 'FAILED' },
      'INSPECTOR',
      generateIdempotencyKey('pr16b')
    );

    const stopWorkRes = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(stopWorkRes);
    expect(unwrap(stopWorkRes.body).posture).toBe('STOP_WORK');

    const workItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemRes);
    const etag = unwrap(workItemRes.body).etag;

    await postWithIfMatch(
      `/projects/${P}/work_items/${W}/cancel`,
      {},
      etag,
      'FOREMAN',
      generateIdempotencyKey('pr16c')
    );

    const res = await getAs(`/projects/${P}`, 'FOREMAN');

    expectSuccess(res);
    const project = unwrap(res.body);
    expect(project.posture).toBe('OPEN');
  });

  test('PROJECT_017: Work item in IN_PROGRESS updates labor_committed_hours and causes REVIEW when under 20 available', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const createRes = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'Big2',
        trade: 'GENERAL',
        zone: 'ZONE_C',
        criticality: 'STANDARD',
        estimated_hours: 110,
      },
      'FOREMAN',
      generateIdempotencyKey('pr17')
    );
    expectSuccess(createRes);
    const W = unwrap(createRes.body).id;

    const getRes1 = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(getRes1);
    const EW = unwrap(getRes1.body).etag;

    const readyRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/ready`,
      {},
      EW,
      'FOREMAN',
      generateIdempotencyKey('pr17b')
    );
    expectSuccess(readyRes);

    const inspRes = await postAs(
      `/projects/${P}/inspections`,
      { work_item_id: W, kind: 'SAFETY' },
      'INSPECTOR',
      generateIdempotencyKey('pr17s1')
    );
    expectSuccess(inspRes);
    const IS = unwrap(inspRes.body).id;

    const submitRes = await postAs(
      `/projects/${P}/inspections/${IS}/submit`,
      { outcome: 'PASSED' },
      'INSPECTOR',
      generateIdempotencyKey('pr17s2')
    );
    expectSuccess(submitRes);

    const getRes2 = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(getRes2);
    const EW2 = unwrap(getRes2.body).etag;

    const startRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/start`,
      {},
      EW2,
      'FOREMAN',
      generateIdempotencyKey('pr17c')
    );
    expectSuccess(startRes);

    const res = await getAs(`/projects/${P}`, 'MANAGER');

    expectSuccess(res);
    const project = unwrap(res.body);
    expect(project.labor_committed_hours).toBe(110);
    expect(project.labor_reserved_hours).toBe(0);
    expect(project.labor_available_hours).toBe(10);
    expect(project.posture).toBe('REVIEW');
  });

  test('PROJECT_018: Replacing a revoked permit with a new granted permit restores OPEN posture', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const permit1Res = await postAs(
      `/projects/${P}/permits`,
      { trade: 'ELECTRICAL' },
      'MANAGER',
      generateIdempotencyKey('pr18')
    );
    expectSuccess(permit1Res);
    const PE = unwrap(permit1Res.body).id;

    await postAs(
      `/projects/${P}/permits/${PE}/decide`,
      { decision: 'GRANT' },
      'MANAGER',
      generateIdempotencyKey('pr18b')
    );

    await postAs(
      `/projects/${P}/permits/${PE}/decide`,
      { decision: 'REVOKE' },
      'MANAGER',
      generateIdempotencyKey('pr18c')
    );

    const permit2Res = await postAs(
      `/projects/${P}/permits`,
      { trade: 'ELECTRICAL', replaces_permit_id: PE },
      'MANAGER',
      generateIdempotencyKey('pr18d')
    );
    expectSuccess(permit2Res);
    const PE2 = unwrap(permit2Res.body).id;

    await postAs(
      `/projects/${P}/permits/${PE2}/decide`,
      { decision: 'GRANT' },
      'MANAGER',
      generateIdempotencyKey('pr18e')
    );

    const res = await getAs(`/projects/${P}`, 'FOREMAN');

    expectSuccess(res);
    const project = unwrap(res.body);
    expect(project.posture).toBe('OPEN');

    const electricalPermits = project.permits.filter((p: any) => p.trade === 'ELECTRICAL');
    expect(electricalPermits.length).toBeGreaterThanOrEqual(1);

    const currentPermit = electricalPermits.find((p: any) => p.id === PE2);
    expect(currentPermit).toBeDefined();
    expect(currentPermit.status).toBe('GRANTED');
  });

});
