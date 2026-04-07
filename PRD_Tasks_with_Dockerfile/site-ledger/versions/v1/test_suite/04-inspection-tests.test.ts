import { getAs, postAs, postWithIfMatch, generateIdempotencyKey } from '../../../test-helpers/api-client';
import { expectSuccess, expectErrorCode } from '../../../test-helpers/assertions';
import {
  createProject,
  getProject,
  createWorkItem,
  getWorkItem,
  readyWorkItem,
  startWorkItem,
  cancelWorkItem,
  createPermit,
  decidePermit,
  createInspection,
  submitInspection,
  voidInspection,
  uniqueId,
  unwrap,
} from '../../../test-helpers/resources';
import {
  FX_INPROGRESS_ELECTRICAL_ITEM,
  FX_PLANNED_QUALITY_ON_ELECTRICAL,
  FX_PLANNED_SAFETY_ON_ELECTRICAL,
  FX_FAILED_QUALITY_ON_ELECTRICAL,
  FX_FAILED_SAFETY_ON_ELECTRICAL,
  FX_READY_ELECTRICAL_ITEM,
  FX_TWO_ACTIVE_QUALITY_FAILS,
} from '../../../test-helpers/fixtures';

describe('Feature 4: Inspection Tests', () => {

  test('INSP_001: Creating QUALITY inspection on in-progress work item sets latest_quality_status=PLANNED', async () => {

    const { P, W } = await FX_INPROGRESS_ELECTRICAL_ITEM();

    const res = await postAs(
      `/projects/${P}/inspections`,
      {
        work_item_id: W,
        kind: 'QUALITY',
      },
      'INSPECTOR',
      generateIdempotencyKey('i1')
    );

    expectSuccess(res);

    const workItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemRes);
    expect(unwrap(workItemRes.body).latest_quality_status).toBe('PLANNED');
  });

  test('INSP_002: FOREMAN creating inspection - state consistency invariant', async () => {

    const { P, W } = await FX_INPROGRESS_ELECTRICAL_ITEM();

    const initialWorkItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(initialWorkItemRes);
    const initialQualityStatus = unwrap(initialWorkItemRes.body).latest_quality_status;

    const res = await postAs(
      `/projects/${P}/inspections`,
      {
        work_item_id: W,
        kind: 'QUALITY',
      },
      'FOREMAN',
      generateIdempotencyKey('i2')
    );

    const workItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemRes);
    const finalQualityStatus = unwrap(workItemRes.body).latest_quality_status;

    if (res.status >= 400) {
      expect(finalQualityStatus).toBe(initialQualityStatus);
    } else {
      expect(finalQualityStatus).toBe('PLANNED');
    }
  });

  test('INSP_003: Invalid kind FINAL fails with ERR_BAD_REQUEST', async () => {

    const { P, W } = await FX_INPROGRESS_ELECTRICAL_ITEM();

    const initialWorkItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(initialWorkItemRes);
    const initialState = unwrap(initialWorkItemRes.body);

    const res = await postAs(
      `/projects/${P}/inspections`,
      {
        work_item_id: W,
        kind: 'FINAL',
      },
      'INSPECTOR',
      generateIdempotencyKey('i3')
    );

    expectErrorCode(res, 'ERR_BAD_REQUEST');

    const workItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemRes);
    const workItem = unwrap(workItemRes.body);
    expect(workItem.latest_quality_status).toBe(initialState.latest_quality_status);
    expect(workItem.latest_safety_status).toBe(initialState.latest_safety_status);
  });

  test('INSP_004: Creating second PLANNED inspection of same kind fails with ERR_INSPECTION_ALREADY_PLANNED', async () => {

    const { P, W } = await FX_INPROGRESS_ELECTRICAL_ITEM();

    const firstRes = await postAs(
      `/projects/${P}/inspections`,
      {
        work_item_id: W,
        kind: 'QUALITY',
      },
      'INSPECTOR',
      generateIdempotencyKey('i4')
    );
    expectSuccess(firstRes);

    const res = await postAs(
      `/projects/${P}/inspections`,
      {
        work_item_id: W,
        kind: 'QUALITY',
      },
      'INSPECTOR',
      generateIdempotencyKey('i4b')
    );

    expectErrorCode(res, 'ERR_INSPECTION_ALREADY_PLANNED');

    const workItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemRes);
    expect(unwrap(workItemRes.body).latest_quality_status).toBe('PLANNED');
  });

  test('INSP_005: Submitting quality inspection with outcome=FAILED sets latest_quality_status=FAILED', async () => {

    const { P, W, IQ } = await FX_PLANNED_QUALITY_ON_ELECTRICAL();

    const res = await postAs(
      `/projects/${P}/inspections/${IQ}/submit`,
      { outcome: 'FAILED' },
      'INSPECTOR',
      generateIdempotencyKey('i5')
    );

    expectSuccess(res);

    const workItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemRes);
    expect(unwrap(workItemRes.body).latest_quality_status).toBe('FAILED');
  });

  test('INSP_006: Submitting quality inspection with outcome=PASSED sets latest_quality_status=PASSED', async () => {

    const { P, W, IQ } = await FX_PLANNED_QUALITY_ON_ELECTRICAL();

    const res = await postAs(
      `/projects/${P}/inspections/${IQ}/submit`,
      { outcome: 'PASSED' },
      'INSPECTOR',
      generateIdempotencyKey('i6')
    );

    expectSuccess(res);

    const workItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemRes);
    expect(unwrap(workItemRes.body).latest_quality_status).toBe('PASSED');
  });

  test('INSP_007: FAILED safety inspection triggers STOP_WORK posture', async () => {

    const { P, IS } = await FX_PLANNED_SAFETY_ON_ELECTRICAL();

    const res = await postAs(
      `/projects/${P}/inspections/${IS}/submit`,
      { outcome: 'FAILED' },
      'INSPECTOR',
      generateIdempotencyKey('i7')
    );

    expectSuccess(res);

    const projectRes = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(projectRes);
    expect(unwrap(projectRes.body).posture).toBe('STOP_WORK');
  });

  test('INSP_008: PASSED safety inspection does not trigger STOP_WORK', async () => {

    const { P, IS } = await FX_PLANNED_SAFETY_ON_ELECTRICAL();

    const res = await postAs(
      `/projects/${P}/inspections/${IS}/submit`,
      { outcome: 'PASSED' },
      'INSPECTOR',
      generateIdempotencyKey('i8')
    );

    expectSuccess(res);

    const projectRes = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(projectRes);
    expect(unwrap(projectRes.body).posture).not.toBe('STOP_WORK');
  });

  test('INSP_009: Inspections can be created in STOP_WORK posture', async () => {

    const { P, W } = await FX_FAILED_SAFETY_ON_ELECTRICAL();

    const projectBefore = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(projectBefore);
    expect(unwrap(projectBefore.body).posture).toBe('STOP_WORK');

    const res = await postAs(
      `/projects/${P}/inspections`,
      {
        work_item_id: W,
        kind: 'SAFETY',
      },
      'INSPECTOR',
      generateIdempotencyKey('i9')
    );

    expectSuccess(res);
    const inspection = unwrap(res.body);
    expect(inspection.id).toBeDefined();
  });

  test('INSP_010: Submitting new PASSED safety inspection clears STOP_WORK posture', async () => {

    const { P, W } = await FX_FAILED_SAFETY_ON_ELECTRICAL();

    const inspectionRes = await postAs(
      `/projects/${P}/inspections`,
      {
        work_item_id: W,
        kind: 'SAFETY',
      },
      'INSPECTOR',
      generateIdempotencyKey('i10')
    );
    expectSuccess(inspectionRes);
    const IS2 = unwrap(inspectionRes.body).id;

    const submitRes = await postAs(
      `/projects/${P}/inspections/${IS2}/submit`,
      { outcome: 'PASSED' },
      'INSPECTOR',
      generateIdempotencyKey('i10b')
    );
    expectSuccess(submitRes);

    const res = await getAs(`/projects/${P}`, 'MANAGER');

    expectSuccess(res);
    expect(unwrap(res.body).posture).not.toBe('STOP_WORK');
  });

  test('INSP_011: FOREMAN submitting inspection - state consistency invariant', async () => {

    const { P, W, IQ } = await FX_PLANNED_QUALITY_ON_ELECTRICAL();

    const res = await postAs(
      `/projects/${P}/inspections/${IQ}/submit`,
      { outcome: 'FAILED' },
      'FOREMAN',
      generateIdempotencyKey('i11')
    );

    const workItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemRes);
    const finalQualityStatus = unwrap(workItemRes.body).latest_quality_status;

    if (res.status >= 400) {
      expect(finalQualityStatus).toBe('PLANNED');
    } else {
      expect(finalQualityStatus).toBe('FAILED');
    }
  });

  test('INSP_012: Submitting already submitted inspection - second submit does not change outcome', async () => {

    const { P, W, IQ } = await FX_PLANNED_QUALITY_ON_ELECTRICAL();

    const firstSubmitRes = await postAs(
      `/projects/${P}/inspections/${IQ}/submit`,
      { outcome: 'FAILED' },
      'INSPECTOR',
      generateIdempotencyKey('i12')
    );
    expectSuccess(firstSubmitRes);

    const res = await postAs(
      `/projects/${P}/inspections/${IQ}/submit`,
      { outcome: 'PASSED' },
      'INSPECTOR',
      generateIdempotencyKey('i12b')
    );

    expect(res.status >= 400 || res.status === 200).toBe(true);

    const workItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemRes);
    expect(unwrap(workItemRes.body).latest_quality_status).toBe('FAILED');
  });

  test('INSP_013: New passing inspection supersedes previous failed inspection', async () => {

    const { P, W } = await FX_FAILED_QUALITY_ON_ELECTRICAL();

    const beforeRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(beforeRes);
    expect(unwrap(beforeRes.body).latest_quality_status).toBe('FAILED');

    const inspectionRes = await postAs(
      `/projects/${P}/inspections`,
      {
        work_item_id: W,
        kind: 'QUALITY',
      },
      'INSPECTOR',
      generateIdempotencyKey('i13')
    );
    expectSuccess(inspectionRes);
    const IQ2 = unwrap(inspectionRes.body).id;

    const submitRes = await postAs(
      `/projects/${P}/inspections/${IQ2}/submit`,
      { outcome: 'PASSED' },
      'INSPECTOR',
      generateIdempotencyKey('i13b')
    );
    expectSuccess(submitRes);

    const res = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');

    expectSuccess(res);
    expect(unwrap(res.body).latest_quality_status).toBe('PASSED');
  });

  test('INSP_014: Manager can void a failed inspection', async () => {

    const { P, W, IQ } = await FX_FAILED_QUALITY_ON_ELECTRICAL();

    const beforeRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(beforeRes);
    expect(unwrap(beforeRes.body).latest_quality_status).toBe('FAILED');

    const res = await postAs(
      `/projects/${P}/inspections/${IQ}/void`,
      { reason: 'Wrong target' },
      'MANAGER',
      generateIdempotencyKey('i14')
    );

    expectSuccess(res);

    const workItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemRes);
    const workItem = unwrap(workItemRes.body);

    expect(workItem.latest_quality_status == null || workItem.latest_quality_status === undefined).toBe(true);
  });

  test('INSP_015: INSPECTOR cannot void inspection (ERR_FORBIDDEN)', async () => {

    const { P, W, IQ } = await FX_FAILED_QUALITY_ON_ELECTRICAL();

    const res = await postAs(
      `/projects/${P}/inspections/${IQ}/void`,
      { reason: 'Mistake' },
      'INSPECTOR',
      generateIdempotencyKey('i15')
    );

    expectErrorCode(res, 'ERR_FORBIDDEN');

    const workItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemRes);
    expect(unwrap(workItemRes.body).latest_quality_status).toBe('FAILED');
  });

  test('INSP_016: Voiding already voided inspection - second void does not change state', async () => {

    const { P, W, IQ } = await FX_FAILED_QUALITY_ON_ELECTRICAL();

    const firstVoidRes = await postAs(
      `/projects/${P}/inspections/${IQ}/void`,
      { reason: 'Bad entry' },
      'MANAGER',
      generateIdempotencyKey('i16')
    );
    expectSuccess(firstVoidRes);

    const afterFirstVoidRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(afterFirstVoidRes);
    const qualityStatusAfterFirstVoid = unwrap(afterFirstVoidRes.body).latest_quality_status;

    const res = await postAs(
      `/projects/${P}/inspections/${IQ}/void`,
      { reason: 'Again' },
      'MANAGER',
      generateIdempotencyKey('i16b')
    );

    expect(res.status >= 400 || res.status === 200).toBe(true);

    const workItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemRes);
    expect(unwrap(workItemRes.body).latest_quality_status).toBe(qualityStatusAfterFirstVoid);
  });

  test('INSP_017: Two active work items with FAILED quality triggers REVIEW posture', async () => {

    const { P } = await FX_TWO_ACTIVE_QUALITY_FAILS();

    const res = await getAs(`/projects/${P}`, 'MANAGER');

    expectSuccess(res);
    expect(unwrap(res.body).posture).toBe('REVIEW');
  });

  test('INSP_018: Cancelling one failed-quality work item clears quality-triggered REVIEW', async () => {

    const { P, W1 } = await FX_TWO_ACTIVE_QUALITY_FAILS();

    const projectBefore = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(projectBefore);
    expect(unwrap(projectBefore.body).posture).toBe('REVIEW');

    expect(unwrap(projectBefore.body).labor_available_hours).toBeGreaterThanOrEqual(20);

    const w1Res = await getAs(`/projects/${P}/work_items/${W1}`, 'FOREMAN');
    expectSuccess(w1Res);
    const currentEtag = unwrap(w1Res.body).etag;

    const cancelRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W1}/cancel`,
      {},
      currentEtag,
      'FOREMAN',
      generateIdempotencyKey('i18')
    );
    expectSuccess(cancelRes);

    const res = await getAs(`/projects/${P}`, 'MANAGER');

    expectSuccess(res);
    expect(unwrap(res.body).posture).toBe('OPEN');
  });

  test('INSP_019: Starting READY work item in STOP_WORK fails with ERR_POSTURE_BLOCKED', async () => {

    const { P, W, EW2 } = await FX_READY_ELECTRICAL_ITEM();

    const startRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/start`,
      {},
      EW2,
      'FOREMAN',
      generateIdempotencyKey('i19_start')
    );
    expectSuccess(startRes);

    const workItem2Res = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'Test work item for posture blocking',
        trade: 'GENERAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 8,
      },
      'FOREMAN',
      generateIdempotencyKey('i19_w2')
    );
    expectSuccess(workItem2Res);
    const W2 = unwrap(workItem2Res.body).id;
    const EW2_draft = unwrap(workItem2Res.body).etag;

    const readyRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W2}/ready`,
      {},
      EW2_draft,
      'FOREMAN',
      generateIdempotencyKey('i19_r2')
    );
    expectSuccess(readyRes);

    const inspectionRes = await postAs(
      `/projects/${P}/inspections`,
      {
        work_item_id: W,
        kind: 'SAFETY',
      },
      'INSPECTOR',
      generateIdempotencyKey('i19')
    );
    expectSuccess(inspectionRes);
    const IS = unwrap(inspectionRes.body).id;

    const submitRes = await postAs(
      `/projects/${P}/inspections/${IS}/submit`,
      { outcome: 'FAILED' },
      'INSPECTOR',
      generateIdempotencyKey('i19b')
    );
    expectSuccess(submitRes);

    const projectRes = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(projectRes);
    expect(unwrap(projectRes.body).posture).toBe('STOP_WORK');

    const w2Res = await getAs(`/projects/${P}/work_items/${W2}`, 'FOREMAN');
    expectSuccess(w2Res);
    const currentEtag = unwrap(w2Res.body).etag;
    expect(unwrap(w2Res.body).status).toBe('READY');

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W2}/start`,
      {},
      currentEtag,
      'FOREMAN',
      generateIdempotencyKey('i19c')
    );

    expectErrorCode(res, 'ERR_POSTURE_BLOCKED');

    const workItemRes = await getAs(`/projects/${P}/work_items/${W2}`, 'FOREMAN');
    expectSuccess(workItemRes);
    expect(unwrap(workItemRes.body).status).toBe('READY');
  });

  test('INSP_020: FAILED quality inspection does not block starting (quality not in start_blockers)', async () => {

    const { P, W, EW2 } = await FX_READY_ELECTRICAL_ITEM();

    const inspectionRes = await postAs(
      `/projects/${P}/inspections`,
      {
        work_item_id: W,
        kind: 'QUALITY',
      },
      'INSPECTOR',
      generateIdempotencyKey('i20')
    );
    expectSuccess(inspectionRes);
    const IQ = unwrap(inspectionRes.body).id;

    const submitRes = await postAs(
      `/projects/${P}/inspections/${IQ}/submit`,
      { outcome: 'FAILED' },
      'INSPECTOR',
      generateIdempotencyKey('i20b')
    );
    expectSuccess(submitRes);

    const workItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemRes);
    const workItem = unwrap(workItemRes.body);
    expect(workItem.is_startable).toBe(true);
    expect(workItem.start_blockers).not.toContain('QUALITY');
    expect(workItem.latest_quality_status).toBe('FAILED');

    const startRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/start`,
      {},
      workItem.etag,
      'FOREMAN',
      generateIdempotencyKey('i20c')
    );

    expectSuccess(startRes);

    const finalWorkItemRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(finalWorkItemRes);
    expect(unwrap(finalWorkItemRes.body).status).toBe('IN_PROGRESS');
    expect(unwrap(finalWorkItemRes.body).latest_quality_status).toBe('FAILED');
  });

});
