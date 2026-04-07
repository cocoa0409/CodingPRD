import {
  get, post, postState, patch, idempotencyKey
} from '../../../test-helpers/api-client';
import {
  expectSuccess, expectError, expectErrorCode, getEtag
} from '../../../test-helpers/assertions';
import {
  createWorkspace, getWorkspace,
  createMatter, getMatter, activateMatter, transitionMatter,
  createCustodian, getCustodian,
  createHold, getHold, issueHold, activateHold, issueAndActivateHold, transitionHold, releaseHold,
  createCollection, getCollection, transitionCollection,
  submitCollection, approveCollection, startCollection, deliverCollection, withdrawCollection,
  uniqueId, unwrap
} from '../../../test-helpers/resources';

describe('Matter Lifecycle and Posture Tests', () => {

  test('MATTER_001: Creating a matter starts in DRAFT status', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });

    const createRes = await post(
      `/workspaces/${workspace.id}/matters`,
      { title: 'New Matter', matter_type: 'LITIGATION' },
      idempotencyKey('m1')
    );
    expectSuccess(createRes);
    const matter = unwrap(createRes.body);

    const matterData = await getMatter(workspace.id, matter.id);
    expect(matterData.status).toBe('DRAFT');
    expect(matterData.matter_type).toBe('LITIGATION');
  });

  test('MATTER_002: Activating matter without active custodian fails with ERR_INVALID_STATE', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });

    const matterData = await getMatter(workspace.id, matter.id);
    const etag = matterData.etag!;

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/state`,
      { to_status: 'ACTIVE' },
      etag,
      idempotencyKey('m2-act')
    );

    await expectErrorCode(res, 'ERR_INVALID_STATE');

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.status).toBe('DRAFT');
  });

  test('MATTER_003: Activating matter with DRAFT court-ordered hold fails with ERR_INVALID_STATE', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);

    const hold = await createHold(workspace.id, matter.id, {
      legal_basis: 'REGULATORY',
      scope: 'ALL_DATA',
      is_court_ordered: true,
      custodian_ids: [custodian.id]
    });
    expect(hold.status).toBe('DRAFT');

    const matterData = await getMatter(workspace.id, matter.id);
    const etag = matterData.etag!;

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/state`,
      { to_status: 'ACTIVE' },
      etag,
      idempotencyKey('m3-act')
    );

    await expectErrorCode(res, 'ERR_INVALID_STATE');

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.status).toBe('DRAFT');
  });

  test('MATTER_004: Active matter with no holds/collections has posture OPEN', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const matterData = await getMatter(workspace.id, matter.id);

    expect(matterData.status).toBe('ACTIVE');
    expect(matterData.posture).toBe('OPEN');
  });

  test('MATTER_005: Issuing a hold changes matter posture to REVIEW', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const holdRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'H-iss',
        legal_basis: 'LITIGATION',
        scope: 'ALL_DATA',
        is_court_ordered: false,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('m5-h1')
    );
    expectSuccess(holdRes);
    const hold = unwrap(holdRes.body);

    const holdData = await getHold(workspace.id, matter.id, hold.id);
    const etag = holdData.etag!;

    const issueRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'ISSUED' },
      etag,
      idempotencyKey('m5-iss')
    );
    expectSuccess(issueRes);

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.posture).toBe('REVIEW');

    const holdAfter = await getHold(workspace.id, matter.id, hold.id);
    expect(holdAfter.status).toBe('ISSUED');
  });

  test('MATTER_006: Activating court-ordered hold freezes matter and locks down workspace', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const holdRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'CourtLit',
        legal_basis: 'REGULATORY',
        scope: 'EMAIL_ONLY',
        is_court_ordered: true,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('m6-h')
    );
    expectSuccess(holdRes);
    const hold = unwrap(holdRes.body);

    let holdData = await getHold(workspace.id, matter.id, hold.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'ISSUED' },
      holdData.etag!,
      idempotencyKey('m6-iss')
    );

    holdData = await getHold(workspace.id, matter.id, hold.id);

    const activateRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'ACTIVE' },
      holdData.etag!,
      idempotencyKey('m6-act')
    );
    expectSuccess(activateRes);

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.posture).toBe('FROZEN');

    const wsAfter = await getWorkspace(workspace.id);
    expect(wsAfter.posture).toBe('LOCKDOWN');
  });

  test('MATTER_007: Closing matter with no active holds/collections succeeds', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const matterData = await getMatter(workspace.id, matter.id);
    const etag = matterData.etag!;

    const closeRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/state`,
      { to_status: 'CLOSED' },
      etag,
      idempotencyKey('m7-close')
    );
    expectSuccess(closeRes);

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.status).toBe('CLOSED');
  });

  test('MATTER_008: Closing matter with ACTIVE hold fails with ERR_MATTER_HAS_ACTIVE_HOLDS', async () => {

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

    const matterData = await getMatter(workspace.id, matter.id);
    const etag = matterData.etag!;

    const closeRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/state`,
      { to_status: 'CLOSED' },
      etag,
      idempotencyKey('m8-close')
    );

    await expectErrorCode(closeRes, 'ERR_MATTER_HAS_ACTIVE_HOLDS');

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.status).toBe('ACTIVE');
  });

  test('MATTER_009: Closing matter with active hold and pending collection fails', async () => {

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

    const collData = await getCollection(workspace.id, matter.id, collection.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'SUBMITTED' },
      collData.etag!,
      idempotencyKey('m9-sub')
    );

    const matterData = await getMatter(workspace.id, matter.id);
    const etag = matterData.etag!;

    const closeRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/state`,
      { to_status: 'CLOSED' },
      etag,
      idempotencyKey('m9-close')
    );

    expectError(closeRes);
    const errorCode = closeRes.body?.data?.error_code;
    expect(['ERR_MATTER_HAS_ACTIVE_HOLDS', 'ERR_MATTER_HAS_PENDING_COLLECTIONS']).toContain(errorCode);

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.status).toBe('ACTIVE');
  });

  test('MATTER_010: Reopening a CLOSED matter succeeds', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    let matterData = await getMatter(workspace.id, matter.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/state`,
      { to_status: 'CLOSED' },
      matterData.etag!,
      idempotencyKey('m10-close')
    );

    matterData = await getMatter(workspace.id, matter.id);
    expect(matterData.status).toBe('CLOSED');

    const reopenRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/state`,
      { to_status: 'ACTIVE' },
      matterData.etag!,
      idempotencyKey('m10-reopen')
    );
    expectSuccess(reopenRes);

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.status).toBe('ACTIVE');
  });

  test('MATTER_011: Transitioning ACTIVE matter back to DRAFT fails with ERR_INVALID_STATE', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const matterData = await getMatter(workspace.id, matter.id);
    const etag = matterData.etag!;

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/state`,
      { to_status: 'DRAFT' },
      etag,
      idempotencyKey('m11')
    );

    await expectErrorCode(res, 'ERR_INVALID_STATE');

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.status).toBe('ACTIVE');
  });

  test('MATTER_012: Renaming a DRAFT matter succeeds', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });

    const matterData = await getMatter(workspace.id, matter.id);
    const etag = matterData.etag!;

    const patchRes = await patch(
      `/workspaces/${workspace.id}/matters/${matter.id}`,
      { title: 'Matter-L1 Renamed' },
      etag,
      idempotencyKey('m12')
    );
    expectSuccess(patchRes);

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.title).toBe('Matter-L1 Renamed');
  });

  test('MATTER_013: matter_type remains unchanged when PATCH attempted on ACTIVE matter', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const matterData = await getMatter(workspace.id, matter.id);
    const etag = matterData.etag!;

    const patchRes = await patch(
      `/workspaces/${workspace.id}/matters/${matter.id}`,
      { matter_type: 'INVESTIGATION' },
      etag,
      idempotencyKey('m13')
    );

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.matter_type).toBe('LITIGATION');
  });

  test('MATTER_014: Skipping ISSUED state when activating hold fails with ERR_INVALID_STATE', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const holdRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'HoldDraft',
        legal_basis: 'LITIGATION',
        scope: 'ALL_DATA',
        is_court_ordered: false,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('m14-h')
    );
    expectSuccess(holdRes);
    const hold = unwrap(holdRes.body);

    const holdData = await getHold(workspace.id, matter.id, hold.id);
    const etag = holdData.etag!;

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'ACTIVE' },
      etag,
      idempotencyKey('m14-act')
    );

    await expectErrorCode(res, 'ERR_INVALID_STATE');

    const holdAfter = await getHold(workspace.id, matter.id, hold.id);
    expect(holdAfter.status).toBe('DRAFT');
  });

  test('MATTER_015: Matter with ACTIVE non-court-ordered hold has posture OPEN', async () => {

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

    const matterData = await getMatter(workspace.id, matter.id);

    expect(matterData.posture).toBe('OPEN');
  });

  test('MATTER_016: Submitting collection changes matter posture to REVIEW', async () => {

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

    const collData = await getCollection(workspace.id, matter.id, collection.id);

    const submitRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'SUBMITTED' },
      collData.etag!,
      idempotencyKey('m16-sub')
    );
    expectSuccess(submitRes);

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.posture).toBe('REVIEW');
    expect(matterAfter.bytes_reserved).toBe(200);
    expect(matterAfter.bytes_stored).toBe(0);
  });

  test('MATTER_017: Withdrawing only submitted collection returns posture to OPEN', async () => {

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
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'SUBMITTED' },
      collData.etag!,
      idempotencyKey('m17-sub')
    );

    collData = await getCollection(workspace.id, matter.id, collection.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'WITHDRAWN' },
      collData.etag!,
      idempotencyKey('m17-wd')
    );

    const matterData = await getMatter(workspace.id, matter.id);

    expect(matterData.posture).toBe('OPEN');
    expect(matterData.bytes_reserved).toBe(0);
  });

  test('MATTER_018: Matter with court-ordered ACTIVE hold has posture FROZEN', async () => {

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

    const matterData = await getMatter(workspace.id, matter.id);

    expect(matterData.posture).toBe('FROZEN');
  });

  test('MATTER_019: Releasing court-ordered hold removes FROZEN posture', async () => {

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

    const matterBefore = await getMatter(workspace.id, matter.id);
    expect(matterBefore.posture).toBe('FROZEN');

    const holdData = await getHold(workspace.id, matter.id, hold.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'RELEASED' },
      holdData.etag!,
      idempotencyKey('m19-rel')
    );

    const matterAfter = await getMatter(workspace.id, matter.id);

    expect(matterAfter.posture).not.toBe('FROZEN');
  });

  test('MATTER_020: Submitted collection reserves capacity on matter', async () => {

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

    const collRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections`,
      {
        hold_id: hold.id,
        custodian_id: custodian.id,
        data_source: 'DRIVE',
        estimated_bytes: 100
      },
      idempotencyKey('m20-c')
    );
    expectSuccess(collRes);
    const collection = unwrap(collRes.body);

    const collData = await getCollection(workspace.id, matter.id, collection.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'SUBMITTED' },
      collData.etag!,
      idempotencyKey('m20-sub')
    );

    const matterData = await getMatter(workspace.id, matter.id);

    expect(matterData.bytes_reserved).toBe(100);
    expect(matterData.bytes_stored).toBe(0);
  });

  test('MATTER_021: Delivered collection converts reservation to stored bytes', async () => {

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

    const collRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections`,
      {
        hold_id: hold.id,
        custodian_id: custodian.id,
        data_source: 'DRIVE',
        estimated_bytes: 100
      },
      idempotencyKey('m21-c')
    );
    expectSuccess(collRes);
    const collection = unwrap(collRes.body);

    let collData = await getCollection(workspace.id, matter.id, collection.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'SUBMITTED' },
      collData.etag!,
      idempotencyKey('m21-sub')
    );

    collData = await getCollection(workspace.id, matter.id, collection.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'APPROVED' },
      collData.etag!,
      idempotencyKey('m21-app')
    );

    collData = await getCollection(workspace.id, matter.id, collection.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'IN_PROGRESS' },
      collData.etag!,
      idempotencyKey('m21-prog')
    );

    collData = await getCollection(workspace.id, matter.id, collection.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'DELIVERED', actual_bytes: 90 },
      collData.etag!,
      idempotencyKey('m21-del')
    );

    const matterData = await getMatter(workspace.id, matter.id);

    expect(matterData.bytes_reserved).toBe(0);
    expect(matterData.bytes_stored).toBe(90);
  });

  test('MATTER_022: CLOSED matter rename behavior', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    let matterData = await getMatter(workspace.id, matter.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/state`,
      { to_status: 'CLOSED' },
      matterData.etag!,
      idempotencyKey('m22-close')
    );

    matterData = await getMatter(workspace.id, matter.id);
    expect(matterData.status).toBe('CLOSED');

    const patchRes = await patch(
      `/workspaces/${workspace.id}/matters/${matter.id}`,
      { title: 'Closed Rename' },
      matterData.etag!,
      idempotencyKey('m22-p')
    );

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.status).toBe('CLOSED');
  });

  test('MATTER_023: Closed matter with no holds/collections has posture OPEN', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const matterData = await getMatter(workspace.id, matter.id);

    const closeRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/state`,
      { to_status: 'CLOSED' },
      matterData.etag!,
      idempotencyKey('m23')
    );
    expectSuccess(closeRes);

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.status).toBe('CLOSED');
    expect(matterAfter.posture).toBe('OPEN');
  });

  test('MATTER_024: INVESTIGATION matter can be created and activated', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'INVESTIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const matterData = await getMatter(workspace.id, matter.id);

    expect(matterData.matter_type).toBe('INVESTIGATION');
    expect(matterData.status).toBe('ACTIVE');
  });

  test('MATTER_025: LITIGATION basis on INVESTIGATION matter without court order is blocked', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'INVESTIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const holdRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'BadBasis',
        legal_basis: 'LITIGATION',
        scope: 'ALL_DATA',
        is_court_ordered: false,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('m25-h')
    );

    if (holdRes.status >= 400) {

      expect(holdRes.body?.data?.error_code).toBe('ERR_BAD_REQUEST');
      return;
    }

    expectSuccess(holdRes);
    const hold = unwrap(holdRes.body);

    const holdData = await getHold(workspace.id, matter.id, hold.id);

    const issueRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'ISSUED' },
      holdData.etag!,
      idempotencyKey('m25-iss')
    );

    await expectErrorCode(issueRes, 'ERR_BAD_REQUEST');

    const holdAfter = await getHold(workspace.id, matter.id, hold.id);
    expect(holdAfter.status).toBe('DRAFT');
  });

  test('MATTER_026: LITIGATION basis on INVESTIGATION matter with court order succeeds at issuance', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'INVESTIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const holdRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'CourtBasis',
        legal_basis: 'LITIGATION',
        scope: 'ALL_DATA',
        is_court_ordered: true,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('m26-h')
    );
    expectSuccess(holdRes);
    const hold = unwrap(holdRes.body);

    const holdData = await getHold(workspace.id, matter.id, hold.id);

    const issueRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'ISSUED' },
      holdData.etag!,
      idempotencyKey('m26-iss')
    );
    expectSuccess(issueRes);

    const holdAfter = await getHold(workspace.id, matter.id, hold.id);
    expect(holdAfter.status).toBe('ISSUED');
  });

  test('MATTER_027: REGULATORY basis on LITIGATION matter without court order is blocked', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const holdRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'BadReg',
        legal_basis: 'REGULATORY',
        scope: 'ALL_DATA',
        is_court_ordered: false,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('m27-h')
    );

    if (holdRes.status >= 400) {

      expect(holdRes.body?.data?.error_code).toBe('ERR_BAD_REQUEST');
      return;
    }

    expectSuccess(holdRes);
    const hold = unwrap(holdRes.body);

    const holdData = await getHold(workspace.id, matter.id, hold.id);

    const issueRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'ISSUED' },
      holdData.etag!,
      idempotencyKey('m27-iss')
    );

    await expectErrorCode(issueRes, 'ERR_BAD_REQUEST');

    const holdAfter = await getHold(workspace.id, matter.id, hold.id);
    expect(holdAfter.status).toBe('DRAFT');
  });

  test('MATTER_028: CONTRACT basis on LITIGATION matter without court order succeeds at issuance', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const holdRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'ContractOK',
        legal_basis: 'CONTRACT',
        scope: 'ALL_DATA',
        is_court_ordered: false,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('m28-h')
    );
    expectSuccess(holdRes);
    const hold = unwrap(holdRes.body);

    const holdData = await getHold(workspace.id, matter.id, hold.id);

    const issueRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'ISSUED' },
      holdData.etag!,
      idempotencyKey('m28-iss')
    );
    expectSuccess(issueRes);

    const holdAfter = await getHold(workspace.id, matter.id, hold.id);
    expect(holdAfter.status).toBe('ISSUED');
  });

  test('MATTER_029: Closing matter returns workspace to NORMAL posture', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const matterData = await getMatter(workspace.id, matter.id);

    const closeRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/state`,
      { to_status: 'CLOSED' },
      matterData.etag!,
      idempotencyKey('m29')
    );
    expectSuccess(closeRes);

    const wsAfter = await getWorkspace(workspace.id);
    expect(wsAfter.posture).toBe('NORMAL');
  });

  test('MATTER_030: Closing DRAFT matter directly fails with ERR_INVALID_STATE', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });

    const matterRes = await post(
      `/workspaces/${workspace.id}/matters`,
      { title: 'M-X', matter_type: 'LITIGATION' },
      idempotencyKey('m30')
    );
    expectSuccess(matterRes);
    const matter = unwrap(matterRes.body);

    const matterData = await getMatter(workspace.id, matter.id);
    const etag = matterData.etag!;

    const closeRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/state`,
      { to_status: 'CLOSED' },
      etag,
      idempotencyKey('m30-close')
    );

    await expectErrorCode(closeRes, 'ERR_INVALID_STATE');

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.status).toBe('DRAFT');
  });

});
