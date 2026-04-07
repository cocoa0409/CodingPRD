import {
  get, post, postState, idempotencyKey
} from '../../../test-helpers/api-client';
import {
  expectSuccess, expectError, expectErrorCode, getEtag
} from '../../../test-helpers/assertions';
import {
  createWorkspace, getWorkspace,
  createMatter, getMatter, activateMatter,
  createCustodian,
  createHold, getHold, issueAndActivateHold, transitionHold,
  createCollection, getCollection, transitionCollection,
  uniqueId, unwrap
} from '../../../test-helpers/resources';

describe('Workspace and Posture Tests', () => {

  test('WORKSPACE_001: Basic workspace creation and retrieval shows NORMAL posture', async () => {

    const createRes = await post('/workspaces', {
      name: `WS-${uniqueId('ws1')}`,
      quota_bytes: 1000
    }, idempotencyKey('ws1'));
    expectSuccess(createRes);
    const workspace = unwrap(createRes.body);

    const getRes = await get(`/workspaces/${workspace.id}`);

    expectSuccess(getRes);
    expect(getRes.body.response_type).toBe('object');
    const data = unwrap(getRes.body);
    expect(data.quota_bytes).toBe(1000);
    expect(data.bytes_reserved).toBe(0);
    expect(data.bytes_stored).toBe(0);
    expect(data.bytes_available).toBe(1000);
    expect(data.posture).toBe('NORMAL');
  });

  test('WORKSPACE_002: Workspace posture becomes REVIEW when bytes_available < 10%', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });

    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const hold = await createHold(workspace.id, matter.id, {
      legal_basis: 'LITIGATION',
      scope: 'ALL_DATA',
      is_court_ordered: false,
      custodian_ids: [custodian.id]
    });
    await issueAndActivateHold(workspace.id, matter.id, hold.id);

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 950
    });

    const collectionData = await getCollection(workspace.id, matter.id, collection.id);
    await transitionCollection(workspace.id, matter.id, collection.id, collectionData.etag!, 'SUBMITTED');

    const ws = await getWorkspace(workspace.id);

    expect(ws.bytes_reserved).toBe(950);
    expect(ws.bytes_stored).toBe(0);
    expect(ws.bytes_available).toBe(50);
    expect(ws.posture).toBe('REVIEW');
  });

  test('WORKSPACE_003: Workspace posture is LOCKDOWN when court-ordered hold is ACTIVE', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });

    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);

    const hold = await createHold(workspace.id, matter.id, {
      legal_basis: 'REGULATORY',
      scope: 'ALL_DATA',
      is_court_ordered: true,
      custodian_ids: [custodian.id]
    });

    await issueAndActivateHold(workspace.id, matter.id, hold.id);
    await activateMatter(workspace.id, matter.id);

    const ws = await getWorkspace(workspace.id);

    expect(ws.posture).toBe('LOCKDOWN');
  });

  test('WORKSPACE_004: Releasing court-ordered hold removes LOCKDOWN posture', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);

    const hold = await createHold(workspace.id, matter.id, {
      legal_basis: 'REGULATORY',
      scope: 'ALL_DATA',
      is_court_ordered: true,
      custodian_ids: [custodian.id]
    });
    await issueAndActivateHold(workspace.id, matter.id, hold.id);
    await activateMatter(workspace.id, matter.id);

    const wsBefore = await getWorkspace(workspace.id);
    expect(wsBefore.posture).toBe('LOCKDOWN');

    const holdData = await getHold(workspace.id, matter.id, hold.id);
    expect(holdData.etag).toBeDefined();

    const releaseRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'RELEASED' },
      holdData.etag!,
      idempotencyKey('ws4-rel')
    );
    expectSuccess(releaseRes);

    const wsAfter = await getWorkspace(workspace.id);
    expect(wsAfter.posture).not.toBe('LOCKDOWN');

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.posture).not.toBe('FROZEN');
  });

  test('WORKSPACE_005: Collection submission blocked when it would exceed quota', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const hold = await createHold(workspace.id, matter.id, {
      legal_basis: 'LITIGATION',
      scope: 'ALL_DATA',
      is_court_ordered: false,
      custodian_ids: [custodian.id]
    });
    await issueAndActivateHold(workspace.id, matter.id, hold.id);

    const c1 = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 600
    });
    const c1Data = await getCollection(workspace.id, matter.id, c1.id);
    await transitionCollection(workspace.id, matter.id, c1.id, c1Data.etag!, 'SUBMITTED');

    const c2 = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'CHAT',
      estimated_bytes: 500
    });
    const c2Data = await getCollection(workspace.id, matter.id, c2.id);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${c2.id}/state`,
      { to_status: 'SUBMITTED' },
      c2Data.etag!,
      idempotencyKey('ws5-s2')
    );

    await expectErrorCode(res, 'ERR_QUOTA_EXCEEDED');

    const ws = await getWorkspace(workspace.id);
    expect(ws.bytes_reserved).toBe(600);
    expect(ws.bytes_stored).toBe(0);
    expect(ws.bytes_available).toBe(400);

    const c2After = await getCollection(workspace.id, matter.id, c2.id);
    expect(c2After.status).toBe('DRAFT');
  });

  test('WORKSPACE_006: Submitted collection reserves capacity', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const hold = await createHold(workspace.id, matter.id, {
      legal_basis: 'LITIGATION',
      scope: 'ALL_DATA',
      is_court_ordered: false,
      custodian_ids: [custodian.id]
    });
    await issueAndActivateHold(workspace.id, matter.id, hold.id);

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'DRIVE',
      estimated_bytes: 200
    });
    const collData = await getCollection(workspace.id, matter.id, collection.id);

    await transitionCollection(workspace.id, matter.id, collection.id, collData.etag!, 'SUBMITTED');

    const ws = await getWorkspace(workspace.id);

    expect(ws.bytes_reserved).toBe(200);
    expect(ws.bytes_stored).toBe(0);
    expect(ws.bytes_available).toBe(800);
  });

  test('WORKSPACE_007: Stale etag rejects DELIVERED transition', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const hold = await createHold(workspace.id, matter.id, {
      legal_basis: 'LITIGATION',
      scope: 'ALL_DATA',
      is_court_ordered: false,
      custodian_ids: [custodian.id]
    });
    await issueAndActivateHold(workspace.id, matter.id, hold.id);

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 200
    });

    let collData = await getCollection(workspace.id, matter.id, collection.id);
    await transitionCollection(workspace.id, matter.id, collection.id, collData.etag!, 'SUBMITTED');

    collData = await getCollection(workspace.id, matter.id, collection.id);
    const directProgressRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'IN_PROGRESS' },
      collData.etag!,
      idempotencyKey('ws7-prog')
    );
    expectError(directProgressRes);

    collData = await getCollection(workspace.id, matter.id, collection.id);
    expect(collData.status).toBe('SUBMITTED');

    await transitionCollection(workspace.id, matter.id, collection.id, collData.etag!, 'APPROVED');

    collData = await getCollection(workspace.id, matter.id, collection.id);
    const approvedEtag = collData.etag!;

    await transitionCollection(workspace.id, matter.id, collection.id, approvedEtag, 'IN_PROGRESS');

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'DELIVERED', actual_bytes: 150 },
      approvedEtag,
      idempotencyKey('ws7-del')
    );

    await expectErrorCode(res, 'ERR_ETAG_MISMATCH');

    const ws = await getWorkspace(workspace.id);
    expect(ws.bytes_reserved).toBe(200);
    expect(ws.bytes_stored).toBe(0);
    expect(ws.bytes_available).toBe(800);

    const collAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collAfter.status).toBe('IN_PROGRESS');
  });

  test('WORKSPACE_008: Delivery replaces reservation with stored bytes', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const hold = await createHold(workspace.id, matter.id, {
      legal_basis: 'LITIGATION',
      scope: 'ALL_DATA',
      is_court_ordered: false,
      custodian_ids: [custodian.id]
    });
    await issueAndActivateHold(workspace.id, matter.id, hold.id);

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 100
    });

    let collData = await getCollection(workspace.id, matter.id, collection.id);
    await transitionCollection(workspace.id, matter.id, collection.id, collData.etag!, 'SUBMITTED');

    collData = await getCollection(workspace.id, matter.id, collection.id);
    await transitionCollection(workspace.id, matter.id, collection.id, collData.etag!, 'APPROVED');

    collData = await getCollection(workspace.id, matter.id, collection.id);
    await transitionCollection(workspace.id, matter.id, collection.id, collData.etag!, 'IN_PROGRESS');

    collData = await getCollection(workspace.id, matter.id, collection.id);

    await transitionCollection(workspace.id, matter.id, collection.id, collData.etag!, 'DELIVERED', 120);

    const ws = await getWorkspace(workspace.id);
    expect(ws.bytes_reserved).toBe(0);
    expect(ws.bytes_stored).toBe(120);
    expect(ws.bytes_available).toBe(880);
  });

  test('WORKSPACE_009: Withdrawn collection releases reservation', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const hold = await createHold(workspace.id, matter.id, {
      legal_basis: 'LITIGATION',
      scope: 'ALL_DATA',
      is_court_ordered: false,
      custodian_ids: [custodian.id]
    });
    await issueAndActivateHold(workspace.id, matter.id, hold.id);

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 200
    });

    let collData = await getCollection(workspace.id, matter.id, collection.id);
    await transitionCollection(workspace.id, matter.id, collection.id, collData.etag!, 'SUBMITTED');

    const wsBefore = await getWorkspace(workspace.id);
    expect(wsBefore.bytes_reserved).toBe(200);

    collData = await getCollection(workspace.id, matter.id, collection.id);

    await transitionCollection(workspace.id, matter.id, collection.id, collData.etag!, 'WITHDRAWN');

    const ws = await getWorkspace(workspace.id);
    expect(ws.bytes_reserved).toBe(0);
    expect(ws.bytes_stored).toBe(0);
    expect(ws.bytes_available).toBe(1000);

    const collAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collAfter.status).toBe('WITHDRAWN');
  });

  test('WORKSPACE_010: Delivery blocked when actual_bytes would exceed quota', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const hold = await createHold(workspace.id, matter.id, {
      legal_basis: 'LITIGATION',
      scope: 'ALL_DATA',
      is_court_ordered: false,
      custodian_ids: [custodian.id]
    });
    await issueAndActivateHold(workspace.id, matter.id, hold.id);

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 400
    });

    let collData = await getCollection(workspace.id, matter.id, collection.id);
    await transitionCollection(workspace.id, matter.id, collection.id, collData.etag!, 'SUBMITTED');

    collData = await getCollection(workspace.id, matter.id, collection.id);
    await transitionCollection(workspace.id, matter.id, collection.id, collData.etag!, 'APPROVED');

    collData = await getCollection(workspace.id, matter.id, collection.id);
    await transitionCollection(workspace.id, matter.id, collection.id, collData.etag!, 'IN_PROGRESS');

    collData = await getCollection(workspace.id, matter.id, collection.id);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'DELIVERED', actual_bytes: 1200 },
      collData.etag!,
      idempotencyKey('ws10-del')
    );

    await expectErrorCode(res, 'ERR_QUOTA_EXCEEDED');

    const ws = await getWorkspace(workspace.id);
    expect(ws.bytes_reserved).toBe(400);
    expect(ws.bytes_stored).toBe(0);
    expect(ws.bytes_available).toBe(600);

    const collAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collAfter.status).toBe('IN_PROGRESS');
  });

  test('WORKSPACE_011: REVIEW posture when stored bytes leave < 10% available', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const hold = await createHold(workspace.id, matter.id, {
      legal_basis: 'LITIGATION',
      scope: 'ALL_DATA',
      is_court_ordered: false,
      custodian_ids: [custodian.id]
    });
    await issueAndActivateHold(workspace.id, matter.id, hold.id);

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'DRIVE',
      estimated_bytes: 900
    });

    let collData = await getCollection(workspace.id, matter.id, collection.id);
    await transitionCollection(workspace.id, matter.id, collection.id, collData.etag!, 'SUBMITTED');

    collData = await getCollection(workspace.id, matter.id, collection.id);
    await transitionCollection(workspace.id, matter.id, collection.id, collData.etag!, 'APPROVED');

    collData = await getCollection(workspace.id, matter.id, collection.id);
    await transitionCollection(workspace.id, matter.id, collection.id, collData.etag!, 'IN_PROGRESS');

    collData = await getCollection(workspace.id, matter.id, collection.id);
    await transitionCollection(workspace.id, matter.id, collection.id, collData.etag!, 'DELIVERED', 920);

    const ws = await getWorkspace(workspace.id);

    expect(ws.bytes_reserved).toBe(0);
    expect(ws.bytes_stored).toBe(920);
    expect(ws.bytes_available).toBe(80);
    expect(ws.posture).toBe('REVIEW');
  });

  test('WORKSPACE_012: Withdrawal restores NORMAL posture', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const hold = await createHold(workspace.id, matter.id, {
      legal_basis: 'LITIGATION',
      scope: 'ALL_DATA',
      is_court_ordered: false,
      custodian_ids: [custodian.id]
    });
    await issueAndActivateHold(workspace.id, matter.id, hold.id);

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'DRIVE',
      estimated_bytes: 901
    });

    let collData = await getCollection(workspace.id, matter.id, collection.id);
    await transitionCollection(workspace.id, matter.id, collection.id, collData.etag!, 'SUBMITTED');

    const wsBefore = await getWorkspace(workspace.id);
    expect(wsBefore.posture).toBe('REVIEW');

    collData = await getCollection(workspace.id, matter.id, collection.id);

    await transitionCollection(workspace.id, matter.id, collection.id, collData.etag!, 'WITHDRAWN');

    const ws = await getWorkspace(workspace.id);
    expect(ws.bytes_reserved).toBe(0);
    expect(ws.bytes_stored).toBe(0);
    expect(ws.bytes_available).toBe(1000);
    expect(ws.posture).toBe('NORMAL');
  });

});
