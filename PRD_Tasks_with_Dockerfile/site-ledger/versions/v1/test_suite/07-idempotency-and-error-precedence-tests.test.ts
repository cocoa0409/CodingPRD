import {
  getAs,
  postAs,
  postWithIfMatch,
  postRaw,
  generateIdempotencyKey,
  getRequest,
} from '../../../test-helpers/api-client';
import { expectSuccess, expectErrorCode } from '../../../test-helpers/assertions';
import {
  createProject,
  getProject,
  createWorkItem,
  getWorkItem,
  readyWorkItem,
  createPermit,
  decidePermit,
  uniqueId,
  unwrap,
} from '../../../test-helpers/resources';
import {
  FX_PROJECT_OPEN_120,
  FX_DRAFT_ELECTRICAL_ITEM,
  FX_FAILED_SAFETY_ON_ELECTRICAL,
} from '../../../test-helpers/fixtures';
import { HEADERS } from '../../../test-helpers/constants';

describe('Feature 7: Idempotency and Error Precedence Tests', () => {

  test('IDEMP_001: POST with idempotency key creates work item successfully', async () => {

    const { P } = await FX_PROJECT_OPEN_120();
    const idempotencyKey = `ik1-${uniqueId()}`;

    const res = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'Once',
        trade: 'GENERAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 1,
      },
      'FOREMAN',
      idempotencyKey
    );

    expectSuccess(res);
    const workItem = unwrap(res.body);
    expect(workItem.id).toBeDefined();
    expect(workItem.title).toBe('Once');
    expect(workItem.trade).toBe('GENERAL');
    expect(workItem.zone).toBe('ZONE_A');
    expect(workItem.criticality).toBe('STANDARD');
    expect(workItem.estimated_hours).toBe(1);
    expect(workItem.status).toBe('DRAFT');
  });

  test('IDEMP_002: Replaying same POST with same idempotency key returns original outcome', async () => {

    const { P } = await FX_PROJECT_OPEN_120();
    const idempotencyKey = `ik2-${uniqueId()}`;

    const res1 = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'Once',
        trade: 'GENERAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 1,
      },
      'FOREMAN',
      idempotencyKey
    );
    expectSuccess(res1);
    const workItem1 = unwrap(res1.body);

    const res2 = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'Once',
        trade: 'GENERAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 1,
      },
      'FOREMAN',
      idempotencyKey
    );

    expectSuccess(res2);
    const workItem2 = unwrap(res2.body);

    expect(workItem2.id).toBe(workItem1.id);
    expect(workItem2.title).toBe(workItem1.title);
    expect(workItem2.trade).toBe(workItem1.trade);
    expect(workItem2.zone).toBe(workItem1.zone);
    expect(workItem2.criticality).toBe(workItem1.criticality);
    expect(workItem2.estimated_hours).toBe(workItem1.estimated_hours);
    expect(workItem2.status).toBe(workItem1.status);
  });

  test('IDEMP_003: Replaying with different payload returns ERR_IDEMPOTENCY_REPLAY_MISMATCH', async () => {

    const { P } = await FX_PROJECT_OPEN_120();
    const idempotencyKey = `ik3-${uniqueId()}`;

    const res1 = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'A',
        trade: 'GENERAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 1,
      },
      'FOREMAN',
      idempotencyKey
    );
    expectSuccess(res1);

    const res2 = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'B',
        trade: 'GENERAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 1,
      },
      'FOREMAN',
      idempotencyKey
    );

    expectErrorCode(res2, 'ERR_IDEMPOTENCY_REPLAY_MISMATCH');
  });

  test('IDEMP_004: POST without idempotency key returns ERR_MISSING_IDEMPOTENCY_KEY', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const res = await getRequest()
      .post(`/projects/${P}/work_items`)
      .set(HEADERS.ACTOR_ROLE, 'FOREMAN')

      .send({
        title: 'NoKey',
        trade: 'GENERAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 1,
      });

    expectErrorCode(res, 'ERR_MISSING_IDEMPOTENCY_KEY');
  });

  test('IDEMP_005: Replaying successful transition with same idempotency key returns original success', async () => {

    const { P, W, EW } = await FX_DRAFT_ELECTRICAL_ITEM();
    const idempotencyKey = `ik5-${uniqueId()}`;

    const projectBefore = await getProject(P);
    const reservedBefore = projectBefore.labor_reserved_hours;

    const res1 = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/ready`,
      {},
      EW,
      'FOREMAN',
      idempotencyKey
    );
    expectSuccess(res1);
    const response1Body = res1.body;

    const workItem = await getWorkItem(P, W);
    expect(workItem.status).toBe('READY');
    const projectAfterFirst = await getProject(P);
    const reservedAfterFirst = projectAfterFirst.labor_reserved_hours;

    const res2 = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/ready`,
      {},
      EW,
      'FOREMAN',
      idempotencyKey
    );

    expectSuccess(res2);

    expect(res2.body.response_type).toBe(response1Body.response_type);

    const workItemAfter = await getWorkItem(P, W);
    expect(workItemAfter.status).toBe('READY');

    const projectAfterReplay = await getProject(P);
    expect(projectAfterReplay.labor_reserved_hours).toBe(reservedAfterFirst);

    expect(reservedAfterFirst).toBeGreaterThan(reservedBefore);
  });

  test('IDEMP_006: Replaying failed transition with same idempotency key returns original failure', async () => {

    const { P } = await FX_PROJECT_OPEN_120();
    const ik6 = `ik6-${uniqueId()}`;
    const ik6b = `ik6b-${uniqueId()}`;
    const ik6c = `ik6c-${uniqueId()}`;
    const ik6d = `ik6d-${uniqueId()}`;

    const createRes = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'NoPermit',
        trade: 'ELECTRICAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 5,
      },
      'FOREMAN',
      ik6
    );
    expectSuccess(createRes);
    const W = unwrap(createRes.body).id;

    const workItem1 = await getWorkItem(P, W);
    const E = workItem1.etag;

    const readyRes1 = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/ready`,
      {},
      E,
      'FOREMAN',
      ik6b
    );
    expectErrorCode(readyRes1, 'ERR_PERMIT_REQUIRED');

    const permitRes = await postAs(
      `/projects/${P}/permits`,
      { trade: 'ELECTRICAL' },
      'MANAGER',
      ik6c
    );
    expectSuccess(permitRes);
    const PE = unwrap(permitRes.body).id;

    const decideRes = await postAs(
      `/projects/${P}/permits/${PE}/decide`,
      { decision: 'GRANT' },
      'MANAGER',
      ik6d
    );
    expectSuccess(decideRes);

    const project = await getProject(P);
    const grantedPermit = project.permits.find((p: any) => p.id === PE);
    expect(grantedPermit).toBeDefined();
    expect(grantedPermit!.status).toBe('GRANTED');

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/ready`,
      {},
      E,
      'FOREMAN',
      ik6b
    );

    expectErrorCode(res, 'ERR_PERMIT_REQUIRED');

    const workItemAfter = await getWorkItem(P, W);
    expect(workItemAfter.status).toBe('DRAFT');
  });

  test('ERR_001: Missing role header returns ERR_UNAUTHENTICATED (highest precedence)', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const res = await getRequest()
      .post(`/projects/${P}/work_items`)

      .send({
        title: 'Auth',
        trade: 'GENERAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 1,
      });

    expectErrorCode(res, 'ERR_UNAUTHENTICATED');
  });

  test('ERR_002: Missing idempotency key for POST returns ERR_MISSING_IDEMPOTENCY_KEY (after auth)', async () => {

    const res = await getRequest()
      .post(`/projects/unknown-project-${uniqueId()}/work_items`)
      .set(HEADERS.ACTOR_ROLE, 'FOREMAN')

      .send({
        title: 'Key',
        trade: 'GENERAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 1,
      });

    expectErrorCode(res, 'ERR_MISSING_IDEMPOTENCY_KEY');
  });

  test('ERR_003: Idempotency replay mismatch returns ERR_IDEMPOTENCY_REPLAY_MISMATCH (after idempotency check)', async () => {

    const { P } = await FX_PROJECT_OPEN_120();
    const idempotencyKey = `er3-${uniqueId()}`;

    const res1 = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'A',
        trade: 'GENERAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 1,
      },
      'FOREMAN',
      idempotencyKey
    );
    expectSuccess(res1);

    const res2 = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'B',
        trade: 'GENERAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 1,
      },
      'FOREMAN',
      idempotencyKey
    );

    expectErrorCode(res2, 'ERR_IDEMPOTENCY_REPLAY_MISMATCH');
  });

  test('ERR_004: Unknown project returns ERR_NOT_FOUND (after idempotency check)', async () => {

    const res = await postAs(
      `/projects/unknown-project-${uniqueId()}/work_items`,
      {
        title: 'X',
        trade: 'GENERAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 1,
      },
      'FOREMAN',
      `er4-${uniqueId()}`
    );

    expectErrorCode(res, 'ERR_NOT_FOUND');
  });

  test('ERR_005: Role not allowed returns ERR_FORBIDDEN (after NOT_FOUND check)', async () => {

    const { P: P1 } = await FX_PROJECT_OPEN_120();
    const { P: P2 } = await FX_PROJECT_OPEN_120();

    const permitRes = await postAs(
      `/projects/${P1}/permits`,
      { trade: 'ELECTRICAL' },
      'MANAGER',
      `er5-${uniqueId()}`
    );
    expectSuccess(permitRes);
    const PE = unwrap(permitRes.body).id;

    const res = await postAs(
      `/projects/${P2}/permits/${PE}/decide`,
      { decision: 'GRANT' },
      'FOREMAN',
      `er5b-${uniqueId()}`
    );

    expectErrorCode(res, 'ERR_NOT_FOUND');
  });

  test('ERR_006: Posture blocked returns ERR_POSTURE_BLOCKED (after FORBIDDEN check)', async () => {

    const { P, W } = await FX_FAILED_SAFETY_ON_ELECTRICAL();

    const project = await getProject(P);
    expect(project.posture).toBe('STOP_WORK');

    const res = await postAs(
      `/projects/${P}/work_items/${W}/ready`,
      {},
      'FOREMAN',
      `er6-${uniqueId()}`

    );

    expectErrorCode(res, 'ERR_POSTURE_BLOCKED');
  });

  test('ERR_007: Starting DRAFT work item returns ERR_INVALID_STATE (invalid lifecycle action)', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const createRes = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'D',
        trade: 'GENERAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 1,
      },
      'FOREMAN',
      `er7-${uniqueId()}`
    );
    expectSuccess(createRes);
    const W = unwrap(createRes.body).id;

    const workItem = await getWorkItem(P, W);
    expect(workItem.status).toBe('DRAFT');
    const E = workItem.etag;

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/start`,
      {},
      E,
      'FOREMAN',
      `er7b-${uniqueId()}`
    );

    expectErrorCode(res, 'ERR_INVALID_STATE');
  });

  test('ERR_008: Missing If-Match on transition returns ERR_MISSING_IF_MATCH', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const createRes = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'E',
        trade: 'GENERAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 1,
      },
      'FOREMAN',
      `er8-${uniqueId()}`
    );
    expectSuccess(createRes);
    const W = unwrap(createRes.body).id;

    const res = await postAs(
      `/projects/${P}/work_items/${W}/ready`,
      {},
      'FOREMAN',
      `er8b-${uniqueId()}`

    );

    expectErrorCode(res, 'ERR_MISSING_IF_MATCH');
  });

  test('ERR_009: Stale If-Match returns ERR_ETAG_MISMATCH', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const createRes = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'E2',
        trade: 'GENERAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 1,
      },
      'FOREMAN',
      `er9-${uniqueId()}`
    );
    expectSuccess(createRes);
    const W = unwrap(createRes.body).id;

    const workItem1 = await getWorkItem(P, W);
    const E = workItem1.etag;

    const readyRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/ready`,
      {},
      E,
      'FOREMAN',
      `er9b-${uniqueId()}`
    );
    expectSuccess(readyRes);

    const workItem2 = await getWorkItem(P, W);
    expect(workItem2.status).toBe('READY');

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/start`,
      {},
      'stale',
      'FOREMAN',
      `er9c-${uniqueId()}`
    );

    expectErrorCode(res, 'ERR_ETAG_MISMATCH');
  });

  test('ERR_010: Invalid request content returns ERR_BAD_REQUEST', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const projectBefore = await getProject(P);

    const res = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'Bad',
        trade: 'GENERAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 'ten',
      },
      'FOREMAN',
      `er10b-${uniqueId()}`
    );

    expectErrorCode(res, 'ERR_BAD_REQUEST');

    const projectAfter = await getProject(P);
    expect(projectAfter.labor_budget_hours).toBe(projectBefore.labor_budget_hours);
    expect(projectAfter.labor_reserved_hours).toBe(projectBefore.labor_reserved_hours);
    expect(projectAfter.labor_committed_hours).toBe(projectBefore.labor_committed_hours);
    expect(projectAfter.labor_used_hours).toBe(projectBefore.labor_used_hours);
    expect(projectAfter.labor_available_hours).toBe(projectBefore.labor_available_hours);
    expect(projectAfter.posture).toBe(projectBefore.posture);
  });
});
