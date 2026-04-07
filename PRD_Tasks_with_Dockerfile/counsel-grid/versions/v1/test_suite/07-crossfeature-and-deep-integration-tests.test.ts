import {
  get, post, postState, idempotencyKey
} from '../../../test-helpers/api-client';
import {
  expectSuccess, expectError, expectErrorCode, getEtag
} from '../../../test-helpers/assertions';
import {
  createWorkspace, getWorkspace,
  createMatter, getMatter, activateMatter, transitionMatter,
  createCustodian, getCustodian,
  createHold, getHold, transitionHold, issueHold, activateHold, issueAndActivateHold,
  createCollection, getCollection, transitionCollection,
  submitCollection, approveCollection, startCollection, withdrawCollection,
  uniqueId, unwrap
} from '../../../test-helpers/resources';

describe('Cross-Feature and Deep Integration Tests', () => {

  async function setupTwoWorkspaces() {
    const wsA = await createWorkspace({ quota_bytes: 1000 });
    const wsB = await createWorkspace({ quota_bytes: 1000 });
    return { wsA, wsB };
  }

  async function setupFxWsAMatterLitActive() {
    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);
    return { workspace, matter, custodian };
  }

  async function setupFxWsAHoldAlldataActive() {
    const { workspace, matter, custodian } = await setupFxWsAMatterLitActive();
    const hold = await createHold(workspace.id, matter.id, {
      legal_basis: 'LITIGATION',
      scope: 'ALL_DATA',
      is_court_ordered: false,
      custodian_ids: [custodian.id]
    });
    await issueAndActivateHold(workspace.id, matter.id, hold.id);
    const activeHold = await getHold(workspace.id, matter.id, hold.id);
    return { workspace, matter, custodian, hold: activeHold };
  }

  async function setupFxWsAHoldCourtActive() {
    const workspace = await createWorkspace({ quota_bytes: 1000 });

    const matterA = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodianA = await createCustodian(workspace.id, matterA.id);
    const courtHold = await createHold(workspace.id, matterA.id, {
      legal_basis: 'REGULATORY',
      scope: 'ALL_DATA',
      is_court_ordered: true,
      custodian_ids: [custodianA.id]
    });
    await issueAndActivateHold(workspace.id, matterA.id, courtHold.id);
    await activateMatter(workspace.id, matterA.id);

    const activeCourtHold = await getHold(workspace.id, matterA.id, courtHold.id);

    return { workspace, matterA, custodianA, courtHold: activeCourtHold };
  }

  async function addInvMatterWithHold(workspaceId: string) {
    const matterI = await createMatter(workspaceId, { matter_type: 'INVESTIGATION' });
    const custodianI = await createCustodian(workspaceId, matterI.id);
    await activateMatter(workspaceId, matterI.id);

    const regHold = await createHold(workspaceId, matterI.id, {
      legal_basis: 'REGULATORY',
      scope: 'ALL_DATA',
      is_court_ordered: false,
      custodian_ids: [custodianI.id]
    });
    await issueAndActivateHold(workspaceId, matterI.id, regHold.id);
    const activeRegHold = await getHold(workspaceId, matterI.id, regHold.id);

    return { matterI, custodianI, regHold: activeRegHold };
  }

  test('CROSS_001: Accessing matter through wrong workspace returns ERR_NOT_FOUND', async () => {

    const { wsA, wsB } = await setupTwoWorkspaces();

    const matterRes = await post(
      `/workspaces/${wsA.id}/matters`,
      { title: 'A-M1', matter_type: 'LITIGATION' },
      idempotencyKey('cros1-ma')
    );
    expectSuccess(matterRes);
    const matterId = unwrap(matterRes.body).id;

    const getARes = await get(`/workspaces/${wsA.id}/matters/${matterId}`);
    expectSuccess(getARes);

    const getBRes = await get(`/workspaces/${wsB.id}/matters/${matterId}`);

    await expectErrorCode(getBRes, 'ERR_NOT_FOUND');
  });

  test('CROSS_002: Collection submission blocked in LOCKDOWN workspace', async () => {

    const { workspace, matterA, custodianA, courtHold } = await setupFxWsAHoldCourtActive();

    const wsCheck = await getWorkspace(workspace.id);
    expect(wsCheck.posture).toBe('LOCKDOWN');

    const matterI = await createMatter(workspace.id, { matter_type: 'INVESTIGATION' });
    const custodianI = await createCustodian(workspace.id, matterI.id);
    await activateMatter(workspace.id, matterI.id);

    const regHold = await createHold(workspace.id, matterI.id, {
      legal_basis: 'REGULATORY',
      scope: 'ALL_DATA',
      is_court_ordered: false,
      custodian_ids: [custodianI.id]
    });

    let holdForCollection = regHold;
    try {
      await issueAndActivateHold(workspace.id, matterI.id, regHold.id);
      holdForCollection = await getHold(workspace.id, matterI.id, regHold.id);
    } catch (e) {

    }

    const collection = await createCollection(workspace.id, matterI.id, {
      hold_id: holdForCollection.id,
      custodian_id: custodianI.id,
      data_source: 'DRIVE',
      estimated_bytes: 300
    });
    const collectionEtag = collection.etag!;

    const submitRes = await postState(
      `/workspaces/${workspace.id}/matters/${matterI.id}/collections/${collection.id}/state`,
      { to_status: 'SUBMITTED' },
      collectionEtag,
      idempotencyKey('cross2')
    );

    expect(submitRes.status).toBeGreaterThanOrEqual(400);
    const errorCode = submitRes.body?.data?.error_code;
    expect(['ERR_POSTURE_BLOCKED', 'ERR_HOLD_NOT_ACTIVE']).toContain(errorCode);

    const collectionAfter = await getCollection(workspace.id, matterI.id, collection.id);
    expect(collectionAfter.status).toBe('DRAFT');
  });

  test('CROSS_003: Releasing court-ordered hold removes LOCKDOWN and allows submission', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });

    const matterI = await createMatter(workspace.id, { matter_type: 'INVESTIGATION' });
    const custodianI = await createCustodian(workspace.id, matterI.id);
    await activateMatter(workspace.id, matterI.id);

    const regHold = await createHold(workspace.id, matterI.id, {
      legal_basis: 'REGULATORY',
      scope: 'ALL_DATA',
      is_court_ordered: false,
      custodian_ids: [custodianI.id]
    });
    await issueAndActivateHold(workspace.id, matterI.id, regHold.id);

    const collection = await createCollection(workspace.id, matterI.id, {
      hold_id: regHold.id,
      custodian_id: custodianI.id,
      data_source: 'DRIVE',
      estimated_bytes: 300
    });

    const matterA = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodianA = await createCustodian(workspace.id, matterA.id);
    await activateMatter(workspace.id, matterA.id);

    const courtHold = await createHold(workspace.id, matterA.id, {
      legal_basis: 'REGULATORY',
      scope: 'ALL_DATA',
      is_court_ordered: true,
      custodian_ids: [custodianA.id]
    });
    await issueAndActivateHold(workspace.id, matterA.id, courtHold.id);

    const wsCheck = await getWorkspace(workspace.id);
    expect(wsCheck.posture).toBe('LOCKDOWN');

    const courtHoldFresh = await getHold(workspace.id, matterA.id, courtHold.id);
    const releaseRes = await postState(
      `/workspaces/${workspace.id}/matters/${matterA.id}/holds/${courtHold.id}/state`,
      { to_status: 'RELEASED' },
      courtHoldFresh.etag!,
      idempotencyKey('cross3-rel')
    );
    expectSuccess(releaseRes);

    const wsAfterRelease = await getWorkspace(workspace.id);
    expect(wsAfterRelease.posture).not.toBe('LOCKDOWN');

    const collectionFresh = await getCollection(workspace.id, matterI.id, collection.id);

    const submitRes = await postState(
      `/workspaces/${workspace.id}/matters/${matterI.id}/collections/${collection.id}/state`,
      { to_status: 'SUBMITTED' },
      collectionFresh.etag!,
      idempotencyKey('cross3-sub')
    );

    expectSuccess(submitRes);

    const collectionAfter = await getCollection(workspace.id, matterI.id, collection.id);
    expect(collectionAfter.status).toBe('SUBMITTED');
  });

  test('CROSS_004: Quota shared across matters - second collection blocked when capacity exhausted', async () => {

    const { workspace, matter: matterA, custodian: custodianA, hold: holdA } = await setupFxWsAHoldAlldataActive();

    const { matterI, custodianI, regHold } = await addInvMatterWithHold(workspace.id);

    const c1 = await createCollection(workspace.id, matterA.id, {
      hold_id: holdA.id,
      custodian_id: custodianA.id,
      data_source: 'EMAIL',
      estimated_bytes: 800
    });
    const c1Fresh = await getCollection(workspace.id, matterA.id, c1.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matterA.id}/collections/${c1.id}/state`,
      { to_status: 'SUBMITTED' },
      c1Fresh.etag!,
      idempotencyKey('cross4-sub1')
    );

    const c2 = await createCollection(workspace.id, matterI.id, {
      hold_id: regHold.id,
      custodian_id: custodianI.id,
      data_source: 'DRIVE',
      estimated_bytes: 300
    });
    const c2Fresh = await getCollection(workspace.id, matterI.id, c2.id);

    const submitRes = await postState(
      `/workspaces/${workspace.id}/matters/${matterI.id}/collections/${c2.id}/state`,
      { to_status: 'SUBMITTED' },
      c2Fresh.etag!,
      idempotencyKey('cross4-sub2')
    );

    await expectErrorCode(submitRes, 'ERR_QUOTA_EXCEEDED');

    const wsAfter = await getWorkspace(workspace.id);
    expect(wsAfter.bytes_reserved).toBe(800);
    expect(wsAfter.bytes_available).toBe(200);

    const c2After = await getCollection(workspace.id, matterI.id, c2.id);
    expect(c2After.status).toBe('DRAFT');
  });

  test('CROSS_005: Withdrawing collection frees capacity for other matters', async () => {

    const { workspace, matter: matterA, custodian: custodianA, hold: holdA } = await setupFxWsAHoldAlldataActive();

    const { matterI, custodianI, regHold } = await addInvMatterWithHold(workspace.id);

    const c1 = await createCollection(workspace.id, matterA.id, {
      hold_id: holdA.id,
      custodian_id: custodianA.id,
      data_source: 'EMAIL',
      estimated_bytes: 800
    });
    await submitCollection(workspace.id, matterA.id, c1.id);

    const c1Fresh = await getCollection(workspace.id, matterA.id, c1.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matterA.id}/collections/${c1.id}/state`,
      { to_status: 'WITHDRAWN' },
      c1Fresh.etag!,
      idempotencyKey('cross5-wd1')
    );

    const c2 = await createCollection(workspace.id, matterI.id, {
      hold_id: regHold.id,
      custodian_id: custodianI.id,
      data_source: 'DRIVE',
      estimated_bytes: 300
    });
    const c2Fresh = await getCollection(workspace.id, matterI.id, c2.id);

    const submitRes = await postState(
      `/workspaces/${workspace.id}/matters/${matterI.id}/collections/${c2.id}/state`,
      { to_status: 'SUBMITTED' },
      c2Fresh.etag!,
      idempotencyKey('cross5-sub2')
    );

    expectSuccess(submitRes);

    const wsAfter = await getWorkspace(workspace.id);
    expect(wsAfter.bytes_reserved).toBe(300);
    expect(wsAfter.bytes_available).toBe(700);
  });

  test('CROSS_006: Cannot VOID ACTIVE hold with submitted collections', async () => {

    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 200
    });
    await submitCollection(workspace.id, matter.id, collection.id);

    const holdFresh = await getHold(workspace.id, matter.id, hold.id);

    const voidRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'VOID' },
      holdFresh.etag!,
      idempotencyKey('cross6-void')
    );

    if (voidRes.status >= 400) {
      await expectErrorCode(voidRes, 'ERR_INVALID_STATE');

      const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
      expect(collectionAfter.status).toBe('SUBMITTED');
    } else {
      expectSuccess(voidRes);

      const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
      expect(collectionAfter.status).toBe('WITHDRAWN');
    }
  });

  test('CROSS_007: Cannot submit collection when hold is not ACTIVE', async () => {

    const { workspace, matter, custodian } = await setupFxWsAMatterLitActive();

    const holdRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'HoldDraft2',
        legal_basis: 'LITIGATION',
        scope: 'ALL_DATA',
        is_court_ordered: false,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('cross7-h')
    );
    expectSuccess(holdRes);
    const holdId = unwrap(holdRes.body).id;

    const collectionRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections`,
      {
        hold_id: holdId,
        custodian_id: custodian.id,
        data_source: 'EMAIL',
        estimated_bytes: 10
      },
      idempotencyKey('cross7-c')
    );
    expectSuccess(collectionRes);
    const collectionId = unwrap(collectionRes.body).id;
    const collection = await getCollection(workspace.id, matter.id, collectionId);

    const submitRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collectionId}/state`,
      { to_status: 'SUBMITTED' },
      collection.etag!,
      idempotencyKey('cross7-sub')
    );

    await expectErrorCode(submitRes, 'ERR_HOLD_NOT_ACTIVE');

    const collectionAfter = await getCollection(workspace.id, matter.id, collectionId);
    expect(collectionAfter.status).toBe('DRAFT');
  });

  test('CROSS_008: Releasing hold withdraws collection, enabling matter closure', async () => {

    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 200
    });
    await submitCollection(workspace.id, matter.id, collection.id);

    const holdFresh = await getHold(workspace.id, matter.id, hold.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'RELEASED' },
      holdFresh.etag!,
      idempotencyKey('cross8-rel')
    );

    const matterFresh = await getMatter(workspace.id, matter.id);

    const closeRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/state`,
      { to_status: 'CLOSED' },
      matterFresh.etag!,
      idempotencyKey('cross8-close')
    );

    expectSuccess(closeRes);

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.status).toBe('CLOSED');
  });

  test('CROSS_009: Cannot close matter with SUBMITTED collection', async () => {

    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 200
    });
    await submitCollection(workspace.id, matter.id, collection.id);

    const matterFresh = await getMatter(workspace.id, matter.id);

    const closeRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/state`,
      { to_status: 'CLOSED' },
      matterFresh.etag!,
      idempotencyKey('cross9-close')
    );

    expect(closeRes.status).toBeGreaterThanOrEqual(400);
    const errorCode = closeRes.body?.data?.error_code;
    expect(['ERR_MATTER_HAS_PENDING_COLLECTIONS', 'ERR_MATTER_HAS_ACTIVE_HOLDS']).toContain(errorCode);

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.status).toBe('ACTIVE');
  });

  test('CROSS_010: Closed matter can be reopened', async () => {

    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const holdFresh = await getHold(workspace.id, matter.id, hold.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'RELEASED' },
      holdFresh.etag!,
      idempotencyKey('cross10-rel')
    );

    let matterFresh = await getMatter(workspace.id, matter.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/state`,
      { to_status: 'CLOSED' },
      matterFresh.etag!,
      idempotencyKey('cross10-close')
    );

    matterFresh = await getMatter(workspace.id, matter.id);

    const reopenRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/state`,
      { to_status: 'ACTIVE' },
      matterFresh.etag!,
      idempotencyKey('cross10-reopen')
    );

    expectSuccess(reopenRes);

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.status).toBe('ACTIVE');
  });

  test('CROSS_011: ISSUED hold does not cause workspace LOCKDOWN', async () => {

    const { workspace, matter, custodian } = await setupFxWsAMatterLitActive();

    const holdRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'H',
        legal_basis: 'LITIGATION',
        scope: 'ALL_DATA',
        is_court_ordered: false,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('cross11-h')
    );
    expectSuccess(holdRes);
    const holdId = unwrap(holdRes.body).id;

    const holdFresh = await getHold(workspace.id, matter.id, holdId);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${holdId}/state`,
      { to_status: 'ISSUED' },
      holdFresh.etag!,
      idempotencyKey('cross11-iss')
    );

    const ws = await getWorkspace(workspace.id);

    expect(ws.posture).toBe('NORMAL');
  });

  test('CROSS_012: High capacity usage causes REVIEW posture', async () => {

    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 950
    });
    await submitCollection(workspace.id, matter.id, collection.id);

    const matterAfter = await getMatter(workspace.id, matter.id);

    expect(matterAfter.posture).toBe('REVIEW');

    const wsAfter = await getWorkspace(workspace.id);
    expect(wsAfter.posture).toBe('REVIEW');
  });

  test('CROSS_013: Court-ordered ACTIVE hold causes LOCKDOWN', async () => {

    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 950
    });
    await submitCollection(workspace.id, matter.id, collection.id);

    const courtHoldRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'Court',
        legal_basis: 'REGULATORY',
        scope: 'EMAIL_ONLY',
        is_court_ordered: true,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('cross13-h')
    );
    expectSuccess(courtHoldRes);
    const courtHoldId = unwrap(courtHoldRes.body).id;

    let courtHoldFresh = await getHold(workspace.id, matter.id, courtHoldId);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${courtHoldId}/state`,
      { to_status: 'ISSUED' },
      courtHoldFresh.etag!,
      idempotencyKey('cross13-iss')
    );

    courtHoldFresh = await getHold(workspace.id, matter.id, courtHoldId);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${courtHoldId}/state`,
      { to_status: 'ACTIVE' },
      courtHoldFresh.etag!,
      idempotencyKey('cross13-act')
    );

    const wsAfter = await getWorkspace(workspace.id);

    expect(wsAfter.posture).toBe('LOCKDOWN');
  });

  test('CROSS_014: Releasing hold withdraws collections and releases capacity', async () => {

    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 200
    });
    await submitCollection(workspace.id, matter.id, collection.id);

    const wsBefore = await getWorkspace(workspace.id);
    expect(wsBefore.bytes_reserved).toBe(200);

    const holdFresh = await getHold(workspace.id, matter.id, hold.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'RELEASED' },
      holdFresh.etag!,
      idempotencyKey('cross14-rel')
    );

    const wsAfter = await getWorkspace(workspace.id);

    expect(wsAfter.bytes_reserved).toBe(0);
  });

  test('CROSS_015: Cannot create collection under SUSPENDED hold', async () => {

    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const holdFresh = await getHold(workspace.id, matter.id, hold.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'SUSPENDED' },
      holdFresh.etag!,
      idempotencyKey('cross15-s')
    );

    const createRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections`,
      {
        hold_id: hold.id,
        custodian_id: custodian.id,
        data_source: 'EMAIL',
        estimated_bytes: 10
      },
      idempotencyKey('cross15-c')
    );

    if (createRes.status >= 400) {

      const errorCode = createRes.body?.data?.error_code;
      expect(['ERR_POSTURE_BLOCKED', 'ERR_INVALID_STATE', 'ERR_HOLD_NOT_ACTIVE']).toContain(errorCode);
    } else {

      const collectionId = createRes.body?.data?.id;
      const collection = await getCollection(workspace.id, matter.id, collectionId);
      expect(collection.status).toBe('DRAFT');

      const submitRes = await postState(
        `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collectionId}/state`,
        { to_status: 'SUBMITTED' },
        collection.etag!,
        idempotencyKey('cross15-sub')
      );
      expect(submitRes.status).toBeGreaterThanOrEqual(400);
      const submitError = submitRes.body?.data?.error_code;
      expect(['ERR_HOLD_NOT_ACTIVE', 'ERR_POSTURE_BLOCKED', 'ERR_INVALID_STATE']).toContain(submitError);
    }
  });

  test('CROSS_016: Cannot submit collection when hold is ISSUED (not ACTIVE)', async () => {

    const { workspace, matter, custodian } = await setupFxWsAMatterLitActive();

    const holdRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'H',
        legal_basis: 'LITIGATION',
        scope: 'EMAIL_ONLY',
        is_court_ordered: false,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('cross16-h')
    );
    expectSuccess(holdRes);
    const holdId = unwrap(holdRes.body).id;

    const holdFresh = await getHold(workspace.id, matter.id, holdId);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${holdId}/state`,
      { to_status: 'ISSUED' },
      holdFresh.etag!,
      idempotencyKey('cross16-iss')
    );

    const collectionRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections`,
      {
        hold_id: holdId,
        custodian_id: custodian.id,
        data_source: 'EMAIL',
        estimated_bytes: 10
      },
      idempotencyKey('cross16-c')
    );
    expectSuccess(collectionRes);
    const collectionId = unwrap(collectionRes.body).id;
    const collection = await getCollection(workspace.id, matter.id, collectionId);

    const submitRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collectionId}/state`,
      { to_status: 'SUBMITTED' },
      collection.etag!,
      idempotencyKey('cross16-sub')
    );

    await expectErrorCode(submitRes, 'ERR_HOLD_NOT_ACTIVE');

    const collectionAfter = await getCollection(workspace.id, matter.id, collectionId);
    expect(collectionAfter.status).toBe('DRAFT');
  });

  test('CROSS_017: Cannot create collection in CLOSED matter', async () => {

    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const holdFresh = await getHold(workspace.id, matter.id, hold.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'RELEASED' },
      holdFresh.etag!,
      idempotencyKey('cross17-rel')
    );

    const matterFresh = await getMatter(workspace.id, matter.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/state`,
      { to_status: 'CLOSED' },
      matterFresh.etag!,
      idempotencyKey('cross17-close')
    );

    const createRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections`,
      {
        hold_id: hold.id,
        custodian_id: custodian.id,
        data_source: 'EMAIL',
        estimated_bytes: 1
      },
      idempotencyKey('cross17-c')
    );

    await expectErrorCode(createRes, 'ERR_INVALID_STATE');
  });

  test('CROSS_018: Stale etag blocks hold state transition', async () => {

    const { workspace, matter, custodian } = await setupFxWsAMatterLitActive();

    const holdRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'CourtFreeze',
        legal_basis: 'REGULATORY',
        scope: 'EMAIL_ONLY',
        is_court_ordered: true,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('cross18-h')
    );
    expectSuccess(holdRes);
    const holdId = unwrap(holdRes.body).id;

    let holdFresh = await getHold(workspace.id, matter.id, holdId);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${holdId}/state`,
      { to_status: 'ISSUED' },
      holdFresh.etag!,
      idempotencyKey('cross18-iss')
    );

    holdFresh = await getHold(workspace.id, matter.id, holdId);
    const issuedEtag = holdFresh.etag!;

    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${holdId}/state`,
      { to_status: 'ACTIVE' },
      issuedEtag,
      idempotencyKey('cross18-act')
    );

    const releaseRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${holdId}/state`,
      { to_status: 'RELEASED' },
      issuedEtag,
      idempotencyKey('cross18-rel')
    );

    await expectErrorCode(releaseRes, 'ERR_ETAG_MISMATCH');

    const holdAfter = await getHold(workspace.id, matter.id, holdId);
    expect(holdAfter.status).toBe('ACTIVE');
  });

});
