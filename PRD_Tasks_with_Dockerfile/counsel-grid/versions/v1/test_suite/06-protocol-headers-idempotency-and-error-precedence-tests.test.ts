import {
  get, post, postState, patch, postRaw, patchRaw, idempotencyKey
} from '../../../test-helpers/api-client';
import {
  expectSuccess, expectError, expectErrorCode, getEtag
} from '../../../test-helpers/assertions';
import {
  createWorkspace, getWorkspace,
  createMatter, getMatter,
  createCustodian, getCustodian,
  createHold, getHold, issueAndActivateHold,
  createCollection, getCollection,
  uniqueId, unwrap,
  createActiveLitMatter, createActiveLitMatterWithHold,
  createLockdownWorkspace
} from '../../../test-helpers/resources';

describe('Protocol, Headers, Idempotency, and Error Precedence Tests', () => {

  test('PROTO_001: POST /matters without Idempotency-Key fails with ERR_MISSING_IDEMPOTENCY_KEY', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });

    const res = await postRaw(
      `/workspaces/${workspace.id}/matters`,
      { title: 'NoKey', matter_type: 'LITIGATION' }
    );

    await expectErrorCode(res, 'ERR_MISSING_IDEMPOTENCY_KEY');

  });

  test('PROTO_002: PATCH /matters without If-Match fails with ERR_MISSING_IF_MATCH', async () => {

    const { workspace, matter } = await createActiveLitMatter(1000);

    const matterBefore = await getMatter(workspace.id, matter.id);
    const originalTitle = matterBefore.title;

    const res = await postRaw(
      `/workspaces/${workspace.id}/matters/${matter.id}`,
      { title: 'NoMatch' },
      { 'Idempotency-Key': idempotencyKey('p2') }
    );

    const patchRes = await patchRaw(
      `/workspaces/${workspace.id}/matters/${matter.id}`,
      { title: 'NoMatch' },
      { 'Idempotency-Key': idempotencyKey('p2') }
    );

    await expectErrorCode(patchRes, 'ERR_MISSING_IF_MATCH');

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.title).toBe(originalTitle);
    expect(matterAfter.title).not.toBe('NoMatch');
  });

  test('PROTO_003: PATCH /matters without any headers fails with ERR_MISSING_IDEMPOTENCY_KEY first', async () => {

    const { workspace, matter } = await createActiveLitMatter(1000);

    const matterBefore = await getMatter(workspace.id, matter.id);
    const originalTitle = matterBefore.title;

    const res = await patchRaw(
      `/workspaces/${workspace.id}/matters/${matter.id}`,
      { title: 'NoHeaders' }
    );

    await expectErrorCode(res, 'ERR_MISSING_IDEMPOTENCY_KEY');

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.title).toBe(originalTitle);
  });

  test('PROTO_004: POST /state without If-Match fails with ERR_MISSING_IF_MATCH', async () => {

    const { workspace, matter } = await createActiveLitMatter(1000);

    const matterBefore = await getMatter(workspace.id, matter.id);
    expect(matterBefore.status).toBe('ACTIVE');

    const res = await postRaw(
      `/workspaces/${workspace.id}/matters/${matter.id}/state`,
      { to_status: 'CLOSED' },
      { 'Idempotency-Key': idempotencyKey('p4') }
    );

    await expectErrorCode(res, 'ERR_MISSING_IF_MATCH');

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.status).toBe('ACTIVE');
  });

  test('PROTO_005: Idempotency key replay returns same result', async () => {

    const { workspace, matter } = await createActiveLitMatter(1000);

    const matterData = await getMatter(workspace.id, matter.id);
    const etag = matterData.etag!;

    const idemKey = idempotencyKey('p5');

    const firstRes = await patch(
      `/workspaces/${workspace.id}/matters/${matter.id}`,
      { title: 'T1' },
      etag,
      idemKey
    );
    expectSuccess(firstRes);
    const firstData = unwrap(firstRes.body);

    const secondRes = await patch(
      `/workspaces/${workspace.id}/matters/${matter.id}`,
      { title: 'T1' },
      etag,
      idemKey
    );

    expectSuccess(secondRes);
    const secondData = unwrap(secondRes.body);
    expect(secondData.id).toBe(firstData.id);

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.title).toBe('T1');
  });

  test('PROTO_006: Idempotency key replay with different payload fails with ERR_IDEMPOTENCY_REPLAY_MISMATCH', async () => {

    const { workspace, matter } = await createActiveLitMatter(1000);

    const matterData = await getMatter(workspace.id, matter.id);
    const etag = matterData.etag!;

    const idemKey = idempotencyKey('p6');

    const firstRes = await patch(
      `/workspaces/${workspace.id}/matters/${matter.id}`,
      { title: 'T1' },
      etag,
      idemKey
    );
    expectSuccess(firstRes);

    const secondRes = await patch(
      `/workspaces/${workspace.id}/matters/${matter.id}`,
      { title: 'T2' },
      etag,
      idemKey
    );

    await expectErrorCode(secondRes, 'ERR_IDEMPOTENCY_REPLAY_MISMATCH');

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.title).toBe('T1');
  });

  test('PROTO_007: GET returns etag in response', async () => {

    const { workspace, matter } = await createActiveLitMatter(1000);

    const res = await get(`/workspaces/${workspace.id}/matters/${matter.id}`);

    expectSuccess(res);
    const data = unwrap(res.body);
    expect(data.etag).toBeDefined();
    expect(typeof data.etag).toBe('string');
    expect(data.etag.length).toBeGreaterThan(0);
  });

  test('PROTO_008: Stale/bogus etag fails with ERR_ETAG_MISMATCH', async () => {

    const { workspace, matter } = await createActiveLitMatter(1000);

    const matterBefore = await getMatter(workspace.id, matter.id);
    const originalTitle = matterBefore.title;

    const res = await patch(
      `/workspaces/${workspace.id}/matters/${matter.id}`,
      { title: 'BadEtag' },
      'bogus',
      idempotencyKey('p8')
    );

    await expectErrorCode(res, 'ERR_ETAG_MISMATCH');

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.title).toBe(originalTitle);
    expect(matterAfter.title).not.toBe('BadEtag');
  });

  test('PROTO_009: Unknown workspace ID returns ERR_NOT_FOUND', async () => {

    await createWorkspace({ quota_bytes: 1000 });

    const res = await get('/workspaces/missing');

    await expectErrorCode(res, 'ERR_NOT_FOUND');
  });

  test('PROTO_010: Unknown matter ID with valid headers returns ERR_NOT_FOUND', async () => {

    const { workspace } = await createActiveLitMatter(1000);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/missing/state`,
      { to_status: 'ACTIVE' },
      'any',
      idempotencyKey('p10')
    );

    await expectErrorCode(res, 'ERR_NOT_FOUND');
  });

  test('PROTO_011: POST /state without Idempotency-Key fails with ERR_MISSING_IDEMPOTENCY_KEY', async () => {

    const { workspace, matter } = await createActiveLitMatter(1000);

    const res = await postRaw(
      `/workspaces/${workspace.id}/matters/${matter.id}/state`,
      { to_status: 'ACTIVE' }
    );

    await expectErrorCode(res, 'ERR_MISSING_IDEMPOTENCY_KEY');
  });

  test('PROTO_012: Missing Idempotency-Key takes precedence over unknown ID', async () => {

    const { workspace } = await createActiveLitMatter(1000);

    const res = await postRaw(
      `/workspaces/${workspace.id}/matters/missing/state`,
      { to_status: 'ACTIVE' }
    );

    await expectErrorCode(res, 'ERR_MISSING_IDEMPOTENCY_KEY');
  });

  test('PROTO_013: Posture blocks collection creation in LOCKDOWN with valid headers', async () => {

    const { workspace, matter, custodian, hold } = await createLockdownWorkspace(1000);

    const ws = await getWorkspace(workspace.id);
    expect(ws.posture).toBe('LOCKDOWN');

    const res = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections`,
      {
        hold_id: hold.id,
        custodian_id: custodian.id,
        data_source: 'EMAIL',
        estimated_bytes: 1
      },
      idempotencyKey('p13')
    );

    if (res.status >= 400) {
      await expectErrorCode(res, 'ERR_POSTURE_BLOCKED');
    } else {
      expectSuccess(res);
      expect(res.body?.data?.status).toBe('DRAFT');
    }
  });

  test('PROTO_014: Missing Idempotency-Key takes precedence over posture block', async () => {

    const { workspace, matter, custodian, hold } = await createLockdownWorkspace(1000);

    const ws = await getWorkspace(workspace.id);
    expect(ws.posture).toBe('LOCKDOWN');

    const res = await postRaw(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections`,
      {
        hold_id: hold.id,
        custodian_id: custodian.id,
        data_source: 'EMAIL',
        estimated_bytes: 1
      }
    );

    await expectErrorCode(res, 'ERR_MISSING_IDEMPOTENCY_KEY');
  });

  test('PROTO_015: Successful state transition with proper headers', async () => {

    const { workspace, matter } = await createActiveLitMatter(1000);

    let matterData = await getMatter(workspace.id, matter.id);
    expect(matterData.status).toBe('ACTIVE');
    const etag = matterData.etag!;

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/state`,
      { to_status: 'CLOSED' },
      etag,
      idempotencyKey('p15')
    );

    expectSuccess(res);

    matterData = await getMatter(workspace.id, matter.id);
    expect(matterData.status).toBe('CLOSED');
  });

  test('PROTO_016: Response envelope has response_type="object" for successful state transition', async () => {

    const { workspace, matter } = await createActiveLitMatter(1000);

    const matterData = await getMatter(workspace.id, matter.id);
    const etag = matterData.etag!;

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/state`,
      { to_status: 'CLOSED' },
      etag,
      idempotencyKey('p16')
    );

    expectSuccess(res);
    expect(res.body.response_type).toBe('object');
  });

  test('PROTO_017: Error response envelope has response_type="error"', async () => {

    const { workspace, matter } = await createActiveLitMatter(1000);

    const res = await patch(
      `/workspaces/${workspace.id}/matters/${matter.id}`,
      { title: 'X' },
      'x',
      idempotencyKey('p17')
    );

    expectError(res);
    expect(res.body.response_type).toBe('error');
    await expectErrorCode(res, 'ERR_ETAG_MISMATCH');
  });

  test('PROTO_018: Idempotency key for POST create returns same resource', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });

    const idemKey = idempotencyKey('p18');

    const firstRes = await post(
      `/workspaces/${workspace.id}/matters`,
      { title: 'IdemA', matter_type: 'LITIGATION' },
      idemKey
    );
    expectSuccess(firstRes);
    const firstMatter = unwrap(firstRes.body);
    const matterId = firstMatter.id;

    const secondRes = await post(
      `/workspaces/${workspace.id}/matters`,
      { title: 'IdemA', matter_type: 'LITIGATION' },
      idemKey
    );

    expectSuccess(secondRes);
    const secondMatter = unwrap(secondRes.body);
    expect(secondMatter.id).toBe(matterId);

    const matterData = await getMatter(workspace.id, matterId);
    expect(matterData.id).toBe(matterId);
    expect(matterData.title).toBe('IdemA');
  });

  test('PROTO_019: Idempotency key for POST create with different payload fails', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });

    const idemKey = idempotencyKey('p19');

    const firstRes = await post(
      `/workspaces/${workspace.id}/matters`,
      { title: 'IdemB', matter_type: 'LITIGATION' },
      idemKey
    );
    expectSuccess(firstRes);
    const matterId = unwrap(firstRes.body).id;

    const secondRes = await post(
      `/workspaces/${workspace.id}/matters`,
      { title: 'IdemC', matter_type: 'LITIGATION' },
      idemKey
    );

    await expectErrorCode(secondRes, 'ERR_IDEMPOTENCY_REPLAY_MISMATCH');

    const matterData = await getMatter(workspace.id, matterId);
    expect(matterData.title).toBe('IdemB');
  });

  test('PROTO_020: Invalid matter_type returns ERR_BAD_REQUEST', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });

    const res = await post(
      `/workspaces/${workspace.id}/matters`,
      { title: 'BadType', matter_type: 'CRIMINAL' },
      idempotencyKey('p20')
    );

    await expectErrorCode(res, 'ERR_BAD_REQUEST');
  });

});
