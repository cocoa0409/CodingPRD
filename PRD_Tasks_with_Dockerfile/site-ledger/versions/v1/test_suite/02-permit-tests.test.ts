import { getAs, postAs, postWithIfMatch, generateIdempotencyKey, postRaw } from '../../../test-helpers/api-client';
import { expectSuccess, expectErrorCode } from '../../../test-helpers/assertions';
import {
  createProject,
  getProject,
  createWorkItem,
  getWorkItem,
  createPermit,
  decidePermit,
  uniqueId,
  unwrap,
} from '../../../test-helpers/resources';
import {
  FX_PROJECT_OPEN_120,
  FX_ELECTRICAL_PERMIT_GRANTED,
  FX_READY_ELECTRICAL_ITEM,
} from '../../../test-helpers/fixtures';
import { HEADERS } from '../../../test-helpers/constants';

describe('Feature 2: Permit Tests', () => {

  test('PERMIT_001: Creating a permit with MANAGER role succeeds and begins in REQUESTED status', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const res = await postAs(
      `/projects/${P}/permits`,
      { trade: 'ELECTRICAL' },
      'MANAGER',
      generateIdempotencyKey('pm1')
    );

    expectSuccess(res);

    const projectRes = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(projectRes);
    const project = unwrap(projectRes.body);
    const electricalPermit = project.permits.find((p: any) => p.trade === 'ELECTRICAL');
    expect(electricalPermit).toBeDefined();
    expect(electricalPermit.status).toBe('REQUESTED');
  });

  test('PERMIT_002: Creating a permit with FOREMAN role - PRD does not explicitly restrict', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const res = await postAs(
      `/projects/${P}/permits`,
      { trade: 'ELECTRICAL' },
      'FOREMAN',
      generateIdempotencyKey('pm2')
    );

    if (res.status >= 200 && res.status < 300) {

      const projectRes = await getAs(`/projects/${P}`, 'MANAGER');
      expectSuccess(projectRes);
      const project = unwrap(projectRes.body);
      const permit = project.permits.find((p: any) => p.trade === 'ELECTRICAL');
      expect(permit).toBeDefined();
    } else {

      expectErrorCode(res, 'ERR_FORBIDDEN');
      const projectRes = await getAs(`/projects/${P}`, 'MANAGER');
      expectSuccess(projectRes);
      const project = unwrap(projectRes.body);
      expect(project.permits.length).toBe(0);
    }
  });

  test('PERMIT_003: Creating a permit with invalid trade (MASONRY) fails with ERR_BAD_REQUEST', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const res = await postAs(
      `/projects/${P}/permits`,
      { trade: 'MASONRY' },
      'MANAGER',
      generateIdempotencyKey('pm3')
    );

    expectErrorCode(res, 'ERR_BAD_REQUEST');

    const projectRes = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(projectRes);
    const project = unwrap(projectRes.body);
    expect(project.permits.length).toBe(0);
  });

  test('PERMIT_004: Creating permit for trade with existing non-revoked permit fails with ERR_PERMIT_ALREADY_EXISTS', async () => {

    const { P, PE } = await FX_ELECTRICAL_PERMIT_GRANTED();

    const res = await postAs(
      `/projects/${P}/permits`,
      { trade: 'ELECTRICAL' },
      'MANAGER',
      generateIdempotencyKey('pm4')
    );

    expectErrorCode(res, 'ERR_PERMIT_ALREADY_EXISTS');

    const projectRes = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(projectRes);
    const project = unwrap(projectRes.body);
    const electricalPermits = project.permits.filter((p: any) => p.trade === 'ELECTRICAL');
    expect(electricalPermits.length).toBe(1);
    expect(electricalPermits[0].status).toBe('GRANTED');
  });

  test('PERMIT_005: Creating permit for revoked trade without replaces_permit_id fails with ERR_PERMIT_REPLACEMENT_REQUIRED', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const permitRes = await postAs(
      `/projects/${P}/permits`,
      { trade: 'ELECTRICAL' },
      'MANAGER',
      generateIdempotencyKey('pm5')
    );
    expectSuccess(permitRes);
    const PE = unwrap(permitRes.body).id;

    await postAs(
      `/projects/${P}/permits/${PE}/decide`,
      { decision: 'REVOKE' },
      'MANAGER',
      generateIdempotencyKey('pm5b')
    );

    const res = await postAs(
      `/projects/${P}/permits`,
      { trade: 'ELECTRICAL' },
      'MANAGER',
      generateIdempotencyKey('pm5c')
    );

    expectErrorCode(res, 'ERR_PERMIT_REPLACEMENT_REQUIRED');

    const projectRes = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(projectRes);
    const project = unwrap(projectRes.body);
    const electricalPermit = project.permits.find((p: any) => p.trade === 'ELECTRICAL');
    expect(electricalPermit).toBeDefined();
    expect(electricalPermit.status).toBe('REVOKED');
  });

  test('PERMIT_006: Creating replacement permit with replaces_permit_id succeeds', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const permitRes = await postAs(
      `/projects/${P}/permits`,
      { trade: 'ELECTRICAL' },
      'MANAGER',
      generateIdempotencyKey('pm6')
    );
    expectSuccess(permitRes);
    const PE = unwrap(permitRes.body).id;

    await postAs(
      `/projects/${P}/permits/${PE}/decide`,
      { decision: 'REVOKE' },
      'MANAGER',
      generateIdempotencyKey('pm6b')
    );

    const res = await postAs(
      `/projects/${P}/permits`,
      { trade: 'ELECTRICAL', replaces_permit_id: PE },
      'MANAGER',
      generateIdempotencyKey('pm6c')
    );

    expectSuccess(res);
    const newPermit = unwrap(res.body);

    const projectRes = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(projectRes);
    const project = unwrap(projectRes.body);

    const currentPermit = project.permits.find((p: any) => p.id === newPermit.id);
    expect(currentPermit).toBeDefined();
    expect(currentPermit.trade).toBe('ELECTRICAL');
    expect(currentPermit.status).toBe('REQUESTED');
    expect(currentPermit.replaces_permit_id).toBe(PE);
  });

  test('PERMIT_007: Granting a REQUESTED permit moves it to GRANTED status', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const permitRes = await postAs(
      `/projects/${P}/permits`,
      { trade: 'ELECTRICAL' },
      'MANAGER',
      generateIdempotencyKey('pm7')
    );
    expectSuccess(permitRes);
    const PE = unwrap(permitRes.body).id;

    const res = await postAs(
      `/projects/${P}/permits/${PE}/decide`,
      { decision: 'GRANT' },
      'MANAGER',
      generateIdempotencyKey('pm7b')
    );

    expectSuccess(res);

    const projectRes = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(projectRes);
    const project = unwrap(projectRes.body);
    const electricalPermit = project.permits.find((p: any) => p.trade === 'ELECTRICAL');
    expect(electricalPermit).toBeDefined();
    expect(electricalPermit.status).toBe('GRANTED');
  });

  test('PERMIT_008: Granting an already GRANTED permit fails with ERR_INVALID_STATE', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const permitRes = await postAs(
      `/projects/${P}/permits`,
      { trade: 'ELECTRICAL' },
      'MANAGER',
      generateIdempotencyKey('pm8')
    );
    expectSuccess(permitRes);
    const PE = unwrap(permitRes.body).id;

    await postAs(
      `/projects/${P}/permits/${PE}/decide`,
      { decision: 'GRANT' },
      'MANAGER',
      generateIdempotencyKey('pm8b')
    );

    const res = await postAs(
      `/projects/${P}/permits/${PE}/decide`,
      { decision: 'GRANT' },
      'MANAGER',
      generateIdempotencyKey('pm8c')
    );

    expectErrorCode(res, 'ERR_INVALID_STATE');

    const projectRes = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(projectRes);
    const project = unwrap(projectRes.body);
    const electricalPermit = project.permits.find((p: any) => p.trade === 'ELECTRICAL');
    expect(electricalPermit).toBeDefined();
    expect(electricalPermit.status).toBe('GRANTED');
  });

  test('PERMIT_009: Revoking a REQUESTED permit moves it to REVOKED - posture stays OPEN without active items', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const permitRes = await postAs(
      `/projects/${P}/permits`,
      { trade: 'ELECTRICAL' },
      'MANAGER',
      generateIdempotencyKey('pm9')
    );
    expectSuccess(permitRes);
    const PE = unwrap(permitRes.body).id;

    const res = await postAs(
      `/projects/${P}/permits/${PE}/decide`,
      { decision: 'REVOKE' },
      'MANAGER',
      generateIdempotencyKey('pm9b')
    );

    expectSuccess(res);

    const projectRes = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(projectRes);
    const project = unwrap(projectRes.body);
    expect(project.posture).toBe('OPEN');

    const electricalPermit = project.permits.find((p: any) => p.trade === 'ELECTRICAL');
    expect(electricalPermit).toBeDefined();
    expect(electricalPermit.status).toBe('REVOKED');
  });

  test('PERMIT_010: Granting replacement permit after revoke returns posture to OPEN', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const permitRes = await postAs(
      `/projects/${P}/permits`,
      { trade: 'ELECTRICAL' },
      'MANAGER',
      generateIdempotencyKey('pm10')
    );
    expectSuccess(permitRes);
    const PE = unwrap(permitRes.body).id;

    await postAs(
      `/projects/${P}/permits/${PE}/decide`,
      { decision: 'REVOKE' },
      'MANAGER',
      generateIdempotencyKey('pm10b')
    );

    const permit2Res = await postAs(
      `/projects/${P}/permits`,
      { trade: 'ELECTRICAL', replaces_permit_id: PE },
      'MANAGER',
      generateIdempotencyKey('pm10c')
    );
    expectSuccess(permit2Res);
    const PE2 = unwrap(permit2Res.body).id;

    const res = await postAs(
      `/projects/${P}/permits/${PE2}/decide`,
      { decision: 'GRANT' },
      'MANAGER',
      generateIdempotencyKey('pm10d')
    );

    expectSuccess(res);

    const projectRes = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(projectRes);
    const project = unwrap(projectRes.body);
    expect(project.posture).toBe('OPEN');

    const currentPermit = project.permits.find((p: any) => p.id === PE2);
    expect(currentPermit).toBeDefined();
    expect(currentPermit.status).toBe('GRANTED');
  });

  test('PERMIT_011: Granting a REVOKED permit fails with ERR_INVALID_STATE', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const permitRes = await postAs(
      `/projects/${P}/permits`,
      { trade: 'ELECTRICAL' },
      'MANAGER',
      generateIdempotencyKey('pm11')
    );
    expectSuccess(permitRes);
    const PE = unwrap(permitRes.body).id;

    await postAs(
      `/projects/${P}/permits/${PE}/decide`,
      { decision: 'REVOKE' },
      'MANAGER',
      generateIdempotencyKey('pm11b')
    );

    const res = await postAs(
      `/projects/${P}/permits/${PE}/decide`,
      { decision: 'GRANT' },
      'MANAGER',
      generateIdempotencyKey('pm11c')
    );

    expectErrorCode(res, 'ERR_INVALID_STATE');

    const projectRes = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(projectRes);
    const project = unwrap(projectRes.body);
    const electricalPermit = project.permits.find((p: any) => p.trade === 'ELECTRICAL');
    expect(electricalPermit).toBeDefined();
    expect(electricalPermit.status).toBe('REVOKED');
  });

  test('PERMIT_012: Deciding on non-existent permit fails with ERR_NOT_FOUND', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const res = await postAs(
      `/projects/${P}/permits/does-not-exist/decide`,
      { decision: 'GRANT' },
      'MANAGER',
      generateIdempotencyKey('pm12')
    );

    expectErrorCode(res, 'ERR_NOT_FOUND');

    const projectRes = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(projectRes);
    const project = unwrap(projectRes.body);
    expect(project.permits.length).toBe(0);
  });

  test('PERMIT_013: Deciding permit with INSPECTOR role fails with ERR_FORBIDDEN', async () => {

    const { P, PE } = await FX_ELECTRICAL_PERMIT_GRANTED();

    const res = await postAs(
      `/projects/${P}/permits/${PE}/decide`,
      { decision: 'REVOKE' },
      'INSPECTOR',
      generateIdempotencyKey('pm13')
    );

    expectErrorCode(res, 'ERR_FORBIDDEN');

    const projectRes = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(projectRes);
    const project = unwrap(projectRes.body);
    const electricalPermit = project.permits.find((p: any) => p.id === PE);
    expect(electricalPermit).toBeDefined();
    expect(electricalPermit.status).toBe('GRANTED');
  });

  test('PERMIT_014: Deciding permit with invalid decision (DENY) fails with ERR_BAD_REQUEST', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const permitRes = await postAs(
      `/projects/${P}/permits`,
      { trade: 'PLUMBING' },
      'MANAGER',
      generateIdempotencyKey('pm14')
    );
    expectSuccess(permitRes);
    const PP = unwrap(permitRes.body).id;

    const res = await postAs(
      `/projects/${P}/permits/${PP}/decide`,
      { decision: 'DENY' },
      'MANAGER',
      generateIdempotencyKey('pm14b')
    );

    expectErrorCode(res, 'ERR_BAD_REQUEST');

    const projectRes = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(projectRes);
    const project = unwrap(projectRes.body);
    const plumbingPermit = project.permits.find((p: any) => p.id === PP);
    expect(plumbingPermit).toBeDefined();
    expect(plumbingPermit.status).toBe('REQUESTED');
  });

  test('PERMIT_015: Creating replacement permit clears STOP_WORK (new current permit is REQUESTED, not REVOKED)', async () => {

    const { P, PE } = await FX_READY_ELECTRICAL_ITEM();

    await postAs(
      `/projects/${P}/permits/${PE}/decide`,
      { decision: 'REVOKE' },
      'MANAGER',
      generateIdempotencyKey('pm15')
    );

    const beforeRes = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(beforeRes);
    expect(unwrap(beforeRes.body).posture).toBe('STOP_WORK');

    const res = await postAs(
      `/projects/${P}/permits`,
      { trade: 'ELECTRICAL', replaces_permit_id: PE },
      'MANAGER',
      generateIdempotencyKey('pm15b')
    );

    expectSuccess(res);

    const projectRes = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(projectRes);
    const project = unwrap(projectRes.body);
    expect(project.posture).toBe('OPEN');

    const newPermit = unwrap(res.body);
    const currentPermit = project.permits.find((p: any) => p.id === newPermit.id);
    expect(currentPermit).toBeDefined();
    expect(currentPermit.status).toBe('REQUESTED');
  });

  test('PERMIT_016: Granting replacement permit with READY item returns posture to OPEN', async () => {

    const { P, PE } = await FX_READY_ELECTRICAL_ITEM();

    await postAs(
      `/projects/${P}/permits/${PE}/decide`,
      { decision: 'REVOKE' },
      'MANAGER',
      generateIdempotencyKey('pm16')
    );

    const permit2Res = await postAs(
      `/projects/${P}/permits`,
      { trade: 'ELECTRICAL', replaces_permit_id: PE },
      'MANAGER',
      generateIdempotencyKey('pm16b')
    );
    expectSuccess(permit2Res);
    const PE2 = unwrap(permit2Res.body).id;

    await postAs(
      `/projects/${P}/permits/${PE2}/decide`,
      { decision: 'GRANT' },
      'MANAGER',
      generateIdempotencyKey('pm16c')
    );

    const res = await getAs(`/projects/${P}`, 'FOREMAN');

    expectSuccess(res);
    const project = unwrap(res.body);
    expect(project.posture).toBe('OPEN');
  });

  test('PERMIT_017: Starting work item with revoked permit fails with ERR_POSTURE_BLOCKED', async () => {

    const { P, PE, W, EW2 } = await FX_READY_ELECTRICAL_ITEM();

    await postAs(
      `/projects/${P}/permits/${PE}/decide`,
      { decision: 'REVOKE' },
      'MANAGER',
      generateIdempotencyKey('pm17')
    );

    const workItemBeforeRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemBeforeRes);
    const currentEtag = unwrap(workItemBeforeRes.body).etag;

    const res = await postWithIfMatch(
      `/projects/${P}/work_items/${W}/start`,
      {},
      currentEtag,
      'FOREMAN',
      generateIdempotencyKey('pm17b')
    );

    expectErrorCode(res, 'ERR_POSTURE_BLOCKED');

    const workItemAfterRes = await getAs(`/projects/${P}/work_items/${W}`, 'FOREMAN');
    expectSuccess(workItemAfterRes);
    expect(unwrap(workItemAfterRes.body).status).toBe('READY');
  });

  test('PERMIT_018: Creating work item with revoked permit (OPEN posture, no active items) succeeds', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const permitRes = await postAs(
      `/projects/${P}/permits`,
      { trade: 'ELECTRICAL' },
      'MANAGER',
      generateIdempotencyKey('pm18')
    );
    expectSuccess(permitRes);
    const PE = unwrap(permitRes.body).id;

    const revokeRes = await postAs(
      `/projects/${P}/permits/${PE}/decide`,
      { decision: 'REVOKE' },
      'MANAGER',
      generateIdempotencyKey('pm18b')
    );
    expectSuccess(revokeRes);

    const projectBefore = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(projectBefore);
    expect(unwrap(projectBefore.body).posture).toBe('OPEN');

    const res = await postAs(
      `/projects/${P}/work_items`,
      {
        title: 'Panel3',
        trade: 'ELECTRICAL',
        zone: 'ZONE_A',
        criticality: 'STANDARD',
        estimated_hours: 5,
      },
      'FOREMAN',
      generateIdempotencyKey('pm18c')
    );

    expectSuccess(res);
    const workItem = unwrap(res.body);
    expect(workItem.status).toBe('DRAFT');
  });

  test('PERMIT_019: Double-revoking replacement permits keeps posture at OPEN (no active items)', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const permitRes = await postAs(
      `/projects/${P}/permits`,
      { trade: 'ELECTRICAL' },
      'MANAGER',
      generateIdempotencyKey('pm19')
    );
    expectSuccess(permitRes);
    const PE = unwrap(permitRes.body).id;

    const revoke1Res = await postAs(
      `/projects/${P}/permits/${PE}/decide`,
      { decision: 'REVOKE' },
      'MANAGER',
      generateIdempotencyKey('pm19b')
    );
    expectSuccess(revoke1Res);

    const permit2Res = await postAs(
      `/projects/${P}/permits`,
      { trade: 'ELECTRICAL', replaces_permit_id: PE },
      'MANAGER',
      generateIdempotencyKey('pm19c')
    );
    expectSuccess(permit2Res);
    const PE2 = unwrap(permit2Res.body).id;

    const revoke2Res = await postAs(
      `/projects/${P}/permits/${PE2}/decide`,
      { decision: 'REVOKE' },
      'MANAGER',
      generateIdempotencyKey('pm19d')
    );
    expectSuccess(revoke2Res);

    const res = await getAs(`/projects/${P}`, 'MANAGER');

    expectSuccess(res);
    const project = unwrap(res.body);
    expect(project.posture).toBe('OPEN');

    const currentPermit = project.permits.find((p: any) => p.id === PE2);
    expect(currentPermit).toBeDefined();
    expect(currentPermit.status).toBe('REVOKED');
  });

  test('PERMIT_020: Creating permit without Idempotency-Key fails with ERR_MISSING_IDEMPOTENCY_KEY', async () => {

    const { P } = await FX_PROJECT_OPEN_120();

    const res = await postRaw(
      `/projects/${P}/permits`,
      { trade: 'ELECTRICAL' },
      { [HEADERS.ACTOR_ROLE]: 'MANAGER' }
    );

    expectErrorCode(res, 'ERR_MISSING_IDEMPOTENCY_KEY');

    const projectRes = await getAs(`/projects/${P}`, 'MANAGER');
    expectSuccess(projectRes);
    const project = unwrap(projectRes.body);
    expect(project.permits.length).toBe(0);
  });

});
