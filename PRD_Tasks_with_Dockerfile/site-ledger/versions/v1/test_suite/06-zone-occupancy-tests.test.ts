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
  uniqueId,
  unwrap,
} from '../../../test-helpers/resources';
import {
  FX_ZONE_A_OCCUPIED_BY_ELECTRICAL,
  FX_INPROGRESS_GENERAL_ITEM_ZONE_A,
} from '../../../test-helpers/fixtures';

describe('Feature 6: Zone Occupancy Tests', () => {

  test('ZONE_001: GET non-GENERAL work item in ZONE_A confirms zone is occupied', async () => {

    const { P, W } = await FX_ZONE_A_OCCUPIED_BY_ELECTRICAL();

    const res = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');

    expectSuccess(res);
    const workItem = unwrap(res.body);
    expect(workItem.status).toBe('IN_PROGRESS');
    expect(workItem.trade).toBe('ELECTRICAL');
    expect(workItem.zone).toBe('ZONE_A');
  });

  test('ZONE_002: Starting another non-GENERAL item in occupied zone fails with ERR_ZONE_OCCUPIED', async () => {

    const { P } = await FX_ZONE_A_OCCUPIED_BY_ELECTRICAL();

    const createRes = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'OtherTradeSameZone',
        trade: 'PLUMBING',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 5,
      },
      'FOREMAN',
      generateIdempotencyKey('z2')
    );
    expectSuccess(createRes);
    const W2 = unwrap(createRes.body).id;

    const getW2Res = await getAs(`/projects/${P}/work_items/${W2}`, 'FOREMAN');
    expectSuccess(getW2Res);
    const E2 = unwrap(getW2Res.body).etag;

    const permitRes = await postAs(
      `/projects/${P}/permits`,
      { trade: 'PLUMBING' },
      'MANAGER',
      generateIdempotencyKey('z2b')
    );
    expectSuccess(permitRes);
    const PP = unwrap(permitRes.body).id;

    const decideRes = await postAs(
      `/projects/${P}/permits/${PP}/decide`,
      { decision: 'GRANT' },
      'MANAGER',
      generateIdempotencyKey('z2c')
    );
    expectSuccess(decideRes);

    const readyRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W2}/ready`,
      {},
      E2,
      'FOREMAN',
      generateIdempotencyKey('z2d')
    );
    expectSuccess(readyRes);

    const getW2bRes = await getAs(`/projects/${P}/work_items/${W2}`, 'FOREMAN');
    expectSuccess(getW2bRes);
    const E2b = unwrap(getW2bRes.body).etag;

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W2}/start`,
      {},
      E2b,
      'FOREMAN',
      generateIdempotencyKey('z2e')
    );

    expectErrorCode(res, 'ERR_ZONE_OCCUPIED');

    const finalW2Res = await getAs(`/projects/${P}/work_items/${W2}`, 'FOREMAN');
    expectSuccess(finalW2Res);
    const finalW2 = unwrap(finalW2Res.body);
    expect(finalW2.status).toBe('READY');
  });

  test('ZONE_003: GENERAL work can start even when non-GENERAL item is in progress in same zone', async () => {

    const { P } = await FX_ZONE_A_OCCUPIED_BY_ELECTRICAL();

    const createRes = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'Gen1',
        trade: 'GENERAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 1,
      },
      'FOREMAN',
      generateIdempotencyKey('z3')
    );
    expectSuccess(createRes);
    const WG = unwrap(createRes.body).id;

    const getWGRes = await getAs(`/projects/${P}/work_items/${WG}`, 'FOREMAN');
    expectSuccess(getWGRes);
    const E = unwrap(getWGRes.body).etag;

    const readyRes = await postWithIfMatch(
      `/projects/${P}/work_items/${WG}/ready`,
      {},
      E,
      'FOREMAN',
      generateIdempotencyKey('z3b')
    );
    expectSuccess(readyRes);

    const getWGRes2 = await getAs(`/projects/${P}/work_items/${WG}`, 'FOREMAN');
    expectSuccess(getWGRes2);
    const E2 = unwrap(getWGRes2.body).etag;

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${WG}/start`,
      {},
      E2,
      'FOREMAN',
      generateIdempotencyKey('z3c')
    );

    expectSuccess(res);

    const finalWGRes = await getAs(`/projects/${P}/work_items/${WG}`, 'FOREMAN');
    expectSuccess(finalWGRes);
    const finalWG = unwrap(finalWGRes.body);
    expect(finalWG.status).toBe('IN_PROGRESS');
  });

  test('ZONE_004: Non-GENERAL item can start when only GENERAL is in progress (GENERAL does not occupy zone)', async () => {

    const { P, WG } = await FX_INPROGRESS_GENERAL_ITEM_ZONE_A();

    const generalRes = await getAs(`/projects/${P}/work_items/${WG}`, 'FOREMAN');
    expectSuccess(generalRes);
    expect(unwrap(generalRes.body).status).toBe('IN_PROGRESS');
    expect(unwrap(generalRes.body).trade).toBe('GENERAL');

    const createRes = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'Elec',
        trade: 'ELECTRICAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 5,
      },
      'FOREMAN',
      generateIdempotencyKey('z4')
    );
    expectSuccess(createRes);
    const W2 = unwrap(createRes.body).id;

    const getW2Res = await getAs(`/projects/${P}/work_items/${W2}`, 'FOREMAN');
    expectSuccess(getW2Res);
    const E2 = unwrap(getW2Res.body).etag;

    const permitRes = await postAs(
      `/projects/${P}/permits`,
      { trade: 'ELECTRICAL' },
      'MANAGER',
      generateIdempotencyKey('z4b')
    );
    expectSuccess(permitRes);
    const PE = unwrap(permitRes.body).id;

    const decideRes = await postAs(
      `/projects/${P}/permits/${PE}/decide`,
      { decision: 'GRANT' },
      'MANAGER',
      generateIdempotencyKey('z4c')
    );
    expectSuccess(decideRes);

    const readyRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W2}/ready`,
      {},
      E2,
      'FOREMAN',
      generateIdempotencyKey('z4d')
    );
    expectSuccess(readyRes);

    const getW2bRes = await getAs(`/projects/${P}/work_items/${W2}`, 'FOREMAN');
    expectSuccess(getW2bRes);
    const E2b = unwrap(getW2bRes.body).etag;

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W2}/start`,
      {},
      E2b,
      'FOREMAN',
      generateIdempotencyKey('z4e')
    );

    expectSuccess(res);

    const finalW2Res = await getAs(`/projects/${P}/work_items/${W2}`, 'FOREMAN');
    expectSuccess(finalW2Res);
    const finalW2 = unwrap(finalW2Res.body);
    expect(finalW2.status).toBe('IN_PROGRESS');
  });

  test('ZONE_005: After completing occupant, zone becomes free for new non-GENERAL starts', async () => {

    const { P, W, EW3 } = await FX_ZONE_A_OCCUPIED_BY_ELECTRICAL();

    const completeRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/complete`,
      { actual_hours: 10 },
      EW3,
      'FOREMAN',
      generateIdempotencyKey('z5')
    );
    expectSuccess(completeRes);

    const originalRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(originalRes);
    expect(unwrap(originalRes.body).status).toBe('DONE');

    const createRes = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'AfterFree',
        trade: 'PLUMBING',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 5,
      },
      'FOREMAN',
      generateIdempotencyKey('z5b')
    );
    expectSuccess(createRes);
    const W2 = unwrap(createRes.body).id;

    const getW2Res = await getAs(`/projects/${P}/work_items/${W2}`, 'FOREMAN');
    expectSuccess(getW2Res);
    const E2 = unwrap(getW2Res.body).etag;

    const permitRes = await postAs(
      `/projects/${P}/permits`,
      { trade: 'PLUMBING' },
      'MANAGER',
      generateIdempotencyKey('z5c')
    );
    expectSuccess(permitRes);
    const PP = unwrap(permitRes.body).id;

    const decideRes = await postAs(
      `/projects/${P}/permits/${PP}/decide`,
      { decision: 'GRANT' },
      'MANAGER',
      generateIdempotencyKey('z5d')
    );
    expectSuccess(decideRes);

    const readyRes = await postWithIfMatch(
      `/projects/${P}/work_items/${W2}/ready`,
      {},
      E2,
      'FOREMAN',
      generateIdempotencyKey('z5e')
    );
    expectSuccess(readyRes);

    const getW2bRes = await getAs(`/projects/${P}/work_items/${W2}`, 'FOREMAN');
    expectSuccess(getW2bRes);
    const E2b = unwrap(getW2bRes.body).etag;

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W2}/start`,
      {},
      E2b,
      'FOREMAN',
      generateIdempotencyKey('z5f')
    );

    expectSuccess(res);

    const finalW2Res = await getAs(`/projects/${P}/work_items/${W2}`, 'FOREMAN');
    expectSuccess(finalW2Res);
    const finalW2 = unwrap(finalW2Res.body);
    expect(finalW2.status).toBe('IN_PROGRESS');
  });

});
