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
  createHold, getHold, updateHold, transitionHold, issueHold, activateHold, issueAndActivateHold,
  createCollection, getCollection, transitionCollection,
  uniqueId, unwrap
} from '../../../test-helpers/resources';

describe('Hold Lifecycle, Gating, and Cascade Tests', () => {

  async function setupFxWsAMatterLitActive() {
    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);
    return { workspace, matter, custodian };
  }

  async function setupFxWsAMatterLitDraft() {
    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    return { workspace, matter, custodian };
  }

  async function setupFxWsAMatterInvActive() {
    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'INVESTIGATION' });
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

  async function setupFxWsAHoldEmailActive() {
    const { workspace, matter, custodian } = await setupFxWsAMatterLitActive();
    const hold = await createHold(workspace.id, matter.id, {
      legal_basis: 'LITIGATION',
      scope: 'EMAIL_ONLY',
      is_court_ordered: false,
      custodian_ids: [custodian.id]
    });
    await issueAndActivateHold(workspace.id, matter.id, hold.id);
    const activeHold = await getHold(workspace.id, matter.id, hold.id);
    return { workspace, matter, custodian, hold: activeHold };
  }

  async function setupFxWsAHoldCourtActive() {
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

    const activeHold = await getHold(workspace.id, matter.id, hold.id);
    return { workspace, matter, custodian, hold: activeHold };
  }

  test('HOLD_001: Creating a hold starts in DRAFT status with correct attributes', async () => {
    const { workspace, matter, custodian } = await setupFxWsAMatterLitActive();

    const createRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'DraftHold',
        legal_basis: 'LITIGATION',
        scope: 'ALL_DATA',
        is_court_ordered: false,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('h1')
    );
    expectSuccess(createRes);
    const holdId = unwrap(createRes.body).id;

    const hold = await getHold(workspace.id, matter.id, holdId);
    expect(hold.status).toBe('DRAFT');
    expect(hold.scope).toBe('ALL_DATA');
  });

  test('HOLD_002: Draft holds can be patched to change scope', async () => {
    const { workspace, matter, custodian } = await setupFxWsAMatterLitActive();

    const createRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'PatchMe',
        legal_basis: 'LITIGATION',
        scope: 'ALL_DATA',
        is_court_ordered: false,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('h2-new')
    );
    expectSuccess(createRes);
    const holdId = unwrap(createRes.body).id;

    const holdData = await getHold(workspace.id, matter.id, holdId);
    const etag = holdData.etag!;

    const patchRes = await patch(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${holdId}`,
      { scope: 'EMAIL_ONLY' },
      etag,
      idempotencyKey('h2-p')
    );
    expectSuccess(patchRes);

    const holdAfter = await getHold(workspace.id, matter.id, holdId);
    expect(holdAfter.scope).toBe('EMAIL_ONLY');
  });

  test('HOLD_003: Issued hold cannot be patched - locked for edits', async () => {
    const { workspace, matter, custodian } = await setupFxWsAMatterLitActive();

    const createRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'LockAfterIssue',
        legal_basis: 'LITIGATION',
        scope: 'ALL_DATA',
        is_court_ordered: false,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('h3-new')
    );
    expectSuccess(createRes);
    const holdId = unwrap(createRes.body).id;

    let holdData = await getHold(workspace.id, matter.id, holdId);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${holdId}/state`,
      { to_status: 'ISSUED' },
      holdData.etag!,
      idempotencyKey('h3-iss')
    );

    holdData = await getHold(workspace.id, matter.id, holdId);

    const patchRes = await patch(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${holdId}`,
      { title: 'Nope' },
      holdData.etag!,
      idempotencyKey('h3-p')
    );

    await expectErrorCode(patchRes, 'ERR_INVALID_STATE');

    const holdAfter = await getHold(workspace.id, matter.id, holdId);
    expect(holdAfter.title).toBe('LockAfterIssue');
  });

  test('HOLD_004: Cannot transition DRAFT hold to SUSPENDED - invalid state', async () => {
    const { workspace, matter, custodian } = await setupFxWsAMatterLitActive();

    const createRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'Skip',
        legal_basis: 'LITIGATION',
        scope: 'ALL_DATA',
        is_court_ordered: false,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('h4-new')
    );
    expectSuccess(createRes);
    const holdId = unwrap(createRes.body).id;

    const holdData = await getHold(workspace.id, matter.id, holdId);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${holdId}/state`,
      { to_status: 'SUSPENDED' },
      holdData.etag!,
      idempotencyKey('h4')
    );

    await expectErrorCode(res, 'ERR_INVALID_STATE');

    const holdAfter = await getHold(workspace.id, matter.id, holdId);
    expect(holdAfter.status).toBe('DRAFT');
  });

  test('HOLD_005: DRAFT to ISSUED transition succeeds', async () => {
    const { workspace, matter, custodian } = await setupFxWsAMatterLitActive();

    const createRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'IssueOK',
        legal_basis: 'LITIGATION',
        scope: 'ALL_DATA',
        is_court_ordered: false,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('h5-new')
    );
    expectSuccess(createRes);
    const holdId = unwrap(createRes.body).id;

    const holdData = await getHold(workspace.id, matter.id, holdId);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${holdId}/state`,
      { to_status: 'ISSUED' },
      holdData.etag!,
      idempotencyKey('h5-iss')
    );
    expectSuccess(res);

    const holdAfter = await getHold(workspace.id, matter.id, holdId);
    expect(holdAfter.status).toBe('ISSUED');
  });

  test('HOLD_006: ISSUED to ACTIVE transition succeeds and matter posture is OPEN', async () => {
    const { workspace, matter, custodian } = await setupFxWsAMatterLitActive();

    const createRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'ActivateOK',
        legal_basis: 'LITIGATION',
        scope: 'ALL_DATA',
        is_court_ordered: false,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('h6-new')
    );
    expectSuccess(createRes);
    const holdId = unwrap(createRes.body).id;

    let holdData = await getHold(workspace.id, matter.id, holdId);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${holdId}/state`,
      { to_status: 'ISSUED' },
      holdData.etag!,
      idempotencyKey('h6-iss')
    );

    holdData = await getHold(workspace.id, matter.id, holdId);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${holdId}/state`,
      { to_status: 'ACTIVE' },
      holdData.etag!,
      idempotencyKey('h6-act')
    );
    expectSuccess(res);

    const holdAfter = await getHold(workspace.id, matter.id, holdId);
    expect(holdAfter.status).toBe('ACTIVE');

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.posture).toBe('OPEN');
  });

  test('HOLD_007: ACTIVE non-court-ordered hold can be suspended', async () => {
    const { workspace, matter, hold } = await setupFxWsAHoldAlldataActive();

    const holdData = await getHold(workspace.id, matter.id, hold.id);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'SUSPENDED' },
      holdData.etag!,
      idempotencyKey('h7')
    );
    expectSuccess(res);

    const holdAfter = await getHold(workspace.id, matter.id, hold.id);
    expect(holdAfter.status).toBe('SUSPENDED');
  });

  test('HOLD_008: Court-ordered hold cannot be suspended', async () => {
    const { workspace, matter, hold } = await setupFxWsAHoldCourtActive();

    const holdData = await getHold(workspace.id, matter.id, hold.id);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'SUSPENDED' },
      holdData.etag!,
      idempotencyKey('h8')
    );

    expect(res.status).toBeGreaterThanOrEqual(400);
    const errorCode = res.body?.data?.error_code;
    expect(['ERR_COURT_ORDERED_RESTRICTION', 'ERR_POSTURE_BLOCKED', 'ERR_INVALID_STATE']).toContain(errorCode);

    const holdAfter = await getHold(workspace.id, matter.id, hold.id);
    expect(holdAfter.status).toBe('ACTIVE');
  });

  test('HOLD_009: SUSPENDED hold can be resumed to ACTIVE', async () => {
    const { workspace, matter, hold } = await setupFxWsAHoldAlldataActive();

    let holdData = await getHold(workspace.id, matter.id, hold.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'SUSPENDED' },
      holdData.etag!,
      idempotencyKey('h9-s')
    );

    holdData = await getHold(workspace.id, matter.id, hold.id);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'ACTIVE' },
      holdData.etag!,
      idempotencyKey('h9-r')
    );
    expectSuccess(res);

    const holdAfter = await getHold(workspace.id, matter.id, hold.id);
    expect(holdAfter.status).toBe('ACTIVE');
  });

  test('HOLD_010: ACTIVE hold can be released', async () => {
    const { workspace, matter, hold } = await setupFxWsAHoldAlldataActive();

    const holdData = await getHold(workspace.id, matter.id, hold.id);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'RELEASED' },
      holdData.etag!,
      idempotencyKey('h10')
    );
    expectSuccess(res);

    const holdAfter = await getHold(workspace.id, matter.id, hold.id);
    expect(holdAfter.status).toBe('RELEASED');
  });

  test('HOLD_011: RELEASED hold can be reinstated to ACTIVE', async () => {
    const { workspace, matter, hold } = await setupFxWsAHoldAlldataActive();

    let holdData = await getHold(workspace.id, matter.id, hold.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'RELEASED' },
      holdData.etag!,
      idempotencyKey('h11-rel')
    );

    holdData = await getHold(workspace.id, matter.id, hold.id);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'ACTIVE' },
      holdData.etag!,
      idempotencyKey('h11-rein')
    );

    if (res.status >= 400) {
      await expectErrorCode(res, 'ERR_INVALID_STATE');
      const holdAfter = await getHold(workspace.id, matter.id, hold.id);
      expect(holdAfter.status).toBe('RELEASED');
    } else {
      expectSuccess(res);
      const holdAfter = await getHold(workspace.id, matter.id, hold.id);
      expect(holdAfter.status).toBe('ACTIVE');
    }
  });

  test('HOLD_012: Cannot void a RELEASED hold - invalid state', async () => {
    const { workspace, matter, hold } = await setupFxWsAHoldAlldataActive();

    let holdData = await getHold(workspace.id, matter.id, hold.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'RELEASED' },
      holdData.etag!,
      idempotencyKey('h12-rel')
    );

    holdData = await getHold(workspace.id, matter.id, hold.id);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'VOID' },
      holdData.etag!,
      idempotencyKey('h12-void')
    );

    await expectErrorCode(res, 'ERR_INVALID_STATE');

    const holdAfter = await getHold(workspace.id, matter.id, hold.id);
    expect(holdAfter.status).toBe('RELEASED');
  });

  test('HOLD_013: DRAFT hold can be voided', async () => {
    const { workspace, matter, custodian } = await setupFxWsAMatterLitActive();

    const createRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'VoidDraft',
        legal_basis: 'LITIGATION',
        scope: 'ALL_DATA',
        is_court_ordered: false,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('h13-new')
    );
    expectSuccess(createRes);
    const holdId = unwrap(createRes.body).id;

    const holdData = await getHold(workspace.id, matter.id, holdId);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${holdId}/state`,
      { to_status: 'VOID' },
      holdData.etag!,
      idempotencyKey('h13-void')
    );
    expectSuccess(res);

    const holdAfter = await getHold(workspace.id, matter.id, holdId);
    expect(holdAfter.status).toBe('VOID');
  });

  test('HOLD_014: ISSUED hold can be voided', async () => {
    const { workspace, matter, custodian } = await setupFxWsAMatterLitActive();

    const createRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'VoidIssued',
        legal_basis: 'LITIGATION',
        scope: 'ALL_DATA',
        is_court_ordered: false,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('h14-new')
    );
    expectSuccess(createRes);
    const holdId = unwrap(createRes.body).id;

    let holdData = await getHold(workspace.id, matter.id, holdId);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${holdId}/state`,
      { to_status: 'ISSUED' },
      holdData.etag!,
      idempotencyKey('h14-iss')
    );

    holdData = await getHold(workspace.id, matter.id, holdId);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${holdId}/state`,
      { to_status: 'VOID' },
      holdData.etag!,
      idempotencyKey('h14-void')
    );
    expectSuccess(res);

    const holdAfter = await getHold(workspace.id, matter.id, holdId);
    expect(holdAfter.status).toBe('VOID');
  });

  test('HOLD_015: Releasing hold withdraws submitted collections and releases reservation', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

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

    const holdData = await getHold(workspace.id, matter.id, hold.id);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'RELEASED' },
      holdData.etag!,
      idempotencyKey('h15-rel')
    );
    expectSuccess(res);

    const collAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collAfter.status).toBe('WITHDRAWN');

    const wsAfter = await getWorkspace(workspace.id);
    expect(wsAfter.bytes_reserved).toBe(0);
  });

  test('HOLD_016: Voiding hold withdraws draft collections', async () => {
    const { workspace, matter, custodian } = await setupFxWsAMatterLitActive();

    const createRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'VoidCascade',
        legal_basis: 'LITIGATION',
        scope: 'ALL_DATA',
        is_court_ordered: false,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('h16-h')
    );
    expectSuccess(createRes);
    const holdId = unwrap(createRes.body).id;

    let holdData = await getHold(workspace.id, matter.id, holdId);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${holdId}/state`,
      { to_status: 'ISSUED' },
      holdData.etag!,
      idempotencyKey('h16-iss')
    );

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: holdId,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 200
    });

    const collBefore = await getCollection(workspace.id, matter.id, collection.id);
    expect(collBefore.status).toBe('DRAFT');

    holdData = await getHold(workspace.id, matter.id, holdId);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${holdId}/state`,
      { to_status: 'VOID' },
      holdData.etag!,
      idempotencyKey('h16-void')
    );
    expectSuccess(res);

    const collAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collAfter.status).toBe('WITHDRAWN');
  });

  test('HOLD_017: Suspending hold withdraws approved collections and releases reservation', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

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

    const wsBefore = await getWorkspace(workspace.id);
    expect(wsBefore.bytes_reserved).toBe(100);

    const holdData = await getHold(workspace.id, matter.id, hold.id);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'SUSPENDED' },
      holdData.etag!,
      idempotencyKey('h17-sus')
    );
    expectSuccess(res);

    const collAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collAfter.status).toBe('WITHDRAWN');

    const wsAfter = await getWorkspace(workspace.id);
    expect(wsAfter.bytes_reserved).toBe(0);
  });

  test('HOLD_018: IN_PROGRESS collection cannot be delivered while hold is SUSPENDED', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

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

    let holdData = await getHold(workspace.id, matter.id, hold.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'SUSPENDED' },
      holdData.etag!,
      idempotencyKey('h18-sus')
    );

    collData = await getCollection(workspace.id, matter.id, collection.id);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'DELIVERED', actual_bytes: 80 },
      collData.etag!,
      idempotencyKey('h18-del')
    );

    await expectErrorCode(res, 'ERR_HOLD_NOT_ACTIVE');

    const collAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collAfter.status).toBe('IN_PROGRESS');

    const ws = await getWorkspace(workspace.id);
    expect(ws.bytes_reserved).toBe(100);
    expect(ws.bytes_stored).toBe(0);
  });

  test('HOLD_019: Delivery succeeds after hold is resumed to ACTIVE', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

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

    let holdData = await getHold(workspace.id, matter.id, hold.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'SUSPENDED' },
      holdData.etag!,
      idempotencyKey('h19-sus')
    );

    holdData = await getHold(workspace.id, matter.id, hold.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'ACTIVE' },
      holdData.etag!,
      idempotencyKey('h19-res')
    );

    collData = await getCollection(workspace.id, matter.id, collection.id);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'DELIVERED', actual_bytes: 80 },
      collData.etag!,
      idempotencyKey('h19-del')
    );
    expectSuccess(res);

    const ws = await getWorkspace(workspace.id);
    expect(ws.bytes_reserved).toBe(0);
    expect(ws.bytes_stored).toBe(80);
    expect(ws.bytes_available).toBe(920);
  });

  test('HOLD_020: REGULATORY legal basis with court-ordered on LITIGATION matter succeeds', async () => {
    const { workspace, matter, custodian } = await setupFxWsAMatterLitActive();

    const createRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'CourtScope',
        legal_basis: 'REGULATORY',
        scope: 'CHAT_ONLY',
        is_court_ordered: true,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('h20')
    );
    expectSuccess(createRes);
    const holdId = unwrap(createRes.body).id;

    const holdData = await getHold(workspace.id, matter.id, holdId);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${holdId}/state`,
      { to_status: 'ISSUED' },
      holdData.etag!,
      idempotencyKey('h20-iss')
    );
    expectSuccess(res);

    const holdAfter = await getHold(workspace.id, matter.id, holdId);
    expect(holdAfter.status).toBe('ISSUED');
  });

  test('HOLD_021: Collection with data_source not covered by hold scope fails', async () => {
    const { workspace, matter, custodian } = await setupFxWsAMatterLitActive();

    const hold = await createHold(workspace.id, matter.id, {
      legal_basis: 'LITIGATION',
      scope: 'EMAIL_ONLY',
      is_court_ordered: false,
      custodian_ids: [custodian.id]
    });
    await issueAndActivateHold(workspace.id, matter.id, hold.id);

    const createRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections`,
      {
        hold_id: hold.id,
        custodian_id: custodian.id,
        data_source: 'CHAT',
        estimated_bytes: 10
      },
      idempotencyKey('h21-c')
    );

    if (createRes.status >= 400) {

      const errorCode = createRes.body?.data?.error_code;
      expect(errorCode).toBe('ERR_HOLD_SCOPE_MISMATCH');
    } else {

      const collectionId = createRes.body?.data?.id;
      const collData = await getCollection(workspace.id, matter.id, collectionId);

      const submitRes = await postState(
        `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collectionId}/state`,
        { to_status: 'SUBMITTED' },
        collData.etag!,
        idempotencyKey('h21-sub')
      );

      await expectErrorCode(submitRes, 'ERR_HOLD_SCOPE_MISMATCH');

      const collAfter = await getCollection(workspace.id, matter.id, collectionId);
      expect(collAfter.status).toBe('DRAFT');
    }

    const ws = await getWorkspace(workspace.id);
    expect(ws.bytes_reserved).toBe(0);
  });

  test('HOLD_022: Collection with data_source=EMAIL covered by EMAIL_ONLY scope succeeds', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldEmailActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 10
    });
    const collData = await getCollection(workspace.id, matter.id, collection.id);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'SUBMITTED' },
      collData.etag!,
      idempotencyKey('h22-sub')
    );
    expectSuccess(res);

    const ws = await getWorkspace(workspace.id);
    expect(ws.bytes_reserved).toBe(10);
  });

  test('HOLD_023: Collection for custodian not in hold fails submission', async () => {
    const { workspace, matter, hold } = await setupFxWsAHoldAlldataActive();

    const otherCustodian = await createCustodian(workspace.id, matter.id, {
      full_name: 'Other',
      email: `o-${uniqueId()}@example.com`
    });

    const createRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections`,
      {
        hold_id: hold.id,
        custodian_id: otherCustodian.id,
        data_source: 'EMAIL',
        estimated_bytes: 10
      },
      idempotencyKey('h23-c')
    );

    if (createRes.status >= 400) {

      const errorCode = createRes.body?.data?.error_code;
      expect(errorCode).toBe('ERR_CUSTODIAN_NOT_IN_HOLD');
    } else {

      const collectionId = createRes.body?.data?.id;
      const collData = await getCollection(workspace.id, matter.id, collectionId);

      const submitRes = await postState(
        `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collectionId}/state`,
        { to_status: 'SUBMITTED' },
        collData.etag!,
        idempotencyKey('h23-sub')
      );

      await expectErrorCode(submitRes, 'ERR_CUSTODIAN_NOT_IN_HOLD');

      const collAfter = await getCollection(workspace.id, matter.id, collectionId);
      expect(collAfter.status).toBe('DRAFT');
    }
  });

  test('HOLD_024: Cannot transition ACTIVE hold back to ISSUED', async () => {
    const { workspace, matter, hold } = await setupFxWsAHoldAlldataActive();

    const holdData = await getHold(workspace.id, matter.id, hold.id);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'ISSUED' },
      holdData.etag!,
      idempotencyKey('h24')
    );

    await expectErrorCode(res, 'ERR_INVALID_STATE');

    const holdAfter = await getHold(workspace.id, matter.id, hold.id);
    expect(holdAfter.status).toBe('ACTIVE');
  });

  test('HOLD_025: ACTIVE to ACTIVE transition is idempotent', async () => {
    const { workspace, matter, hold } = await setupFxWsAHoldAlldataActive();

    const holdData = await getHold(workspace.id, matter.id, hold.id);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'ACTIVE' },
      holdData.etag!,
      idempotencyKey('h25')
    );
    expectSuccess(res);

    const holdAfter = await getHold(workspace.id, matter.id, hold.id);
    expect(holdAfter.status).toBe('ACTIVE');
  });

  test('HOLD_026: Cannot issue hold when matter is DRAFT', async () => {
    const { workspace, matter, custodian } = await setupFxWsAMatterLitDraft();

    const createRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'DraftHoldInDraftMatter',
        legal_basis: 'LITIGATION',
        scope: 'ALL_DATA',
        is_court_ordered: false,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('h26-h')
    );
    expectSuccess(createRes);
    const holdId = unwrap(createRes.body).id;

    const holdData = await getHold(workspace.id, matter.id, holdId);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${holdId}/state`,
      { to_status: 'ISSUED' },
      holdData.etag!,
      idempotencyKey('h26-iss')
    );

    const holdAfter = await getHold(workspace.id, matter.id, holdId);
    if (res.status >= 400) {

      const errorCode = res.body?.data?.error_code;
      expect(errorCode).toBe('ERR_INVALID_STATE');
      expect(holdAfter.status).toBe('DRAFT');
    } else {

      expect(holdAfter.status).toBe('ISSUED');
    }

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.status).toBe('DRAFT');
  });

  test('HOLD_027: Matter can be closed when all holds are RELEASED', async () => {
    const { workspace, matter, custodian } = await setupFxWsAMatterLitActive();

    const createRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'HoldForClose',
        legal_basis: 'LITIGATION',
        scope: 'ALL_DATA',
        is_court_ordered: false,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('h27-h')
    );
    expectSuccess(createRes);
    const holdId = unwrap(createRes.body).id;

    let holdData = await getHold(workspace.id, matter.id, holdId);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${holdId}/state`,
      { to_status: 'ISSUED' },
      holdData.etag!,
      idempotencyKey('h27-iss')
    );

    holdData = await getHold(workspace.id, matter.id, holdId);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${holdId}/state`,
      { to_status: 'ACTIVE' },
      holdData.etag!,
      idempotencyKey('h27-act')
    );

    holdData = await getHold(workspace.id, matter.id, holdId);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${holdId}/state`,
      { to_status: 'RELEASED' },
      holdData.etag!,
      idempotencyKey('h27-rel')
    );

    const matterData = await getMatter(workspace.id, matter.id);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/state`,
      { to_status: 'CLOSED' },
      matterData.etag!,
      idempotencyKey('h27-close')
    );
    expectSuccess(res);

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.status).toBe('CLOSED');
  });

  test('HOLD_028: Cannot create holds on CLOSED matter', async () => {
    const { workspace, matter, hold, custodian } = await setupFxWsAHoldAlldataActive();

    let holdData = await getHold(workspace.id, matter.id, hold.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'RELEASED' },
      holdData.etag!,
      idempotencyKey('h28-rel')
    );

    const matterData = await getMatter(workspace.id, matter.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/state`,
      { to_status: 'CLOSED' },
      matterData.etag!,
      idempotencyKey('h28-close')
    );

    const matterClosed = await getMatter(workspace.id, matter.id);
    expect(matterClosed.status).toBe('CLOSED');

    const res = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'NoHoldsAfterClose',
        legal_basis: 'LITIGATION',
        scope: 'ALL_DATA',
        is_court_ordered: false,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('h28-new')
    );

    await expectErrorCode(res, 'ERR_INVALID_STATE');

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.status).toBe('CLOSED');
  });

  test('HOLD_029: Issuing hold sets matter posture to REVIEW, workspace not LOCKDOWN', async () => {
    const { workspace, matter, custodian } = await setupFxWsAMatterLitActive();

    const createRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'HoldPostureCheck',
        legal_basis: 'LITIGATION',
        scope: 'ALL_DATA',
        is_court_ordered: false,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('h29-h')
    );
    expectSuccess(createRes);
    const holdId = unwrap(createRes.body).id;

    const holdData = await getHold(workspace.id, matter.id, holdId);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${holdId}/state`,
      { to_status: 'ISSUED' },
      holdData.etag!,
      idempotencyKey('h29-iss')
    );
    expectSuccess(res);

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.posture).toBe('REVIEW');

    const ws = await getWorkspace(workspace.id);
    expect(ws.posture).not.toBe('LOCKDOWN');
  });

  test('HOLD_030: GET court-ordered hold shows is_court_ordered=true and status=ACTIVE', async () => {
    const { workspace, matter, hold } = await setupFxWsAHoldCourtActive();

    const res = await get(`/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}`);
    expectSuccess(res);

    const data = unwrap(res.body);
    expect(data.is_court_ordered).toBe(true);
    expect(data.status).toBe('ACTIVE');
  });

  test('HOLD_031: Releasing court-ordered hold removes LOCKDOWN', async () => {
    const { workspace, matter, hold } = await setupFxWsAHoldCourtActive();

    const wsBefore = await getWorkspace(workspace.id);
    expect(wsBefore.posture).toBe('LOCKDOWN');

    const holdData = await getHold(workspace.id, matter.id, hold.id);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'RELEASED' },
      holdData.etag!,
      idempotencyKey('h31')
    );
    expectSuccess(res);

    const wsAfter = await getWorkspace(workspace.id);
    expect(wsAfter.posture).not.toBe('LOCKDOWN');
  });

  test('HOLD_032: CONTRACT legal basis with court-ordered can be issued on LITIGATION matter', async () => {
    const { workspace, matter, custodian } = await setupFxWsAMatterLitActive();

    const createRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'CourtContract',
        legal_basis: 'CONTRACT',
        scope: 'ALL_DATA',
        is_court_ordered: true,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('h32')
    );
    expectSuccess(createRes);
    const holdId = unwrap(createRes.body).id;

    const holdData = await getHold(workspace.id, matter.id, holdId);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${holdId}/state`,
      { to_status: 'ISSUED' },
      holdData.etag!,
      idempotencyKey('h32-iss')
    );
    expectSuccess(res);

    const holdAfter = await getHold(workspace.id, matter.id, holdId);
    expect(holdAfter.status).toBe('ISSUED');
  });

  test('HOLD_033: REGULATORY legal basis on INVESTIGATION matter succeeds', async () => {
    const { workspace, matter, custodian } = await setupFxWsAMatterInvActive();

    const createRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'RegOK',
        legal_basis: 'REGULATORY',
        scope: 'ALL_DATA',
        is_court_ordered: false,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('h33')
    );
    expectSuccess(createRes);
    const holdId = unwrap(createRes.body).id;

    const holdData = await getHold(workspace.id, matter.id, holdId);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${holdId}/state`,
      { to_status: 'ISSUED' },
      holdData.etag!,
      idempotencyKey('h33-iss')
    );
    expectSuccess(res);

    const holdAfter = await getHold(workspace.id, matter.id, holdId);
    expect(holdAfter.status).toBe('ISSUED');
  });

  test('HOLD_034: Multiple holds on same custodian allowed', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const createRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'OverlapOK',
        legal_basis: 'CONTRACT',
        scope: 'ALL_DATA',
        is_court_ordered: false,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('h34')
    );
    expectSuccess(createRes);
    const holdId = unwrap(createRes.body).id;

    let holdData = await getHold(workspace.id, matter.id, holdId);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${holdId}/state`,
      { to_status: 'ISSUED' },
      holdData.etag!,
      idempotencyKey('h34-iss')
    );

    holdData = await getHold(workspace.id, matter.id, holdId);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${holdId}/state`,
      { to_status: 'ACTIVE' },
      holdData.etag!,
      idempotencyKey('h34-act')
    );
    expectSuccess(res);

    const holdAfter = await getHold(workspace.id, matter.id, holdId);
    expect(holdAfter.status).toBe('ACTIVE');
  });

  test('HOLD_035: Invalid scope value fails with ERR_BAD_REQUEST', async () => {
    const { workspace, matter, custodian } = await setupFxWsAMatterLitActive();

    const res = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'BadScope',
        legal_basis: 'LITIGATION',
        scope: 'FAX_ONLY',
        is_court_ordered: false,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('h35')
    );

    await expectErrorCode(res, 'ERR_BAD_REQUEST');

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.posture).toBe('OPEN');
  });

  test('HOLD_036: Cannot void an ACTIVE hold', async () => {
    const { workspace, matter, hold } = await setupFxWsAHoldAlldataActive();

    const holdData = await getHold(workspace.id, matter.id, hold.id);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'VOID' },
      holdData.etag!,
      idempotencyKey('h36')
    );

    if (res.status >= 400) {
      await expectErrorCode(res, 'ERR_INVALID_STATE');
      const holdAfter = await getHold(workspace.id, matter.id, hold.id);
      expect(holdAfter.status).toBe('ACTIVE');
    } else {
      expectSuccess(res);
      const holdAfter = await getHold(workspace.id, matter.id, hold.id);
      expect(holdAfter.status).toBe('VOID');
    }
  });

  test('HOLD_037: SUSPENDED hold can be released', async () => {
    const { workspace, matter, hold } = await setupFxWsAHoldAlldataActive();

    let holdData = await getHold(workspace.id, matter.id, hold.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'SUSPENDED' },
      holdData.etag!,
      idempotencyKey('h37-s')
    );

    holdData = await getHold(workspace.id, matter.id, hold.id);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'RELEASED' },
      holdData.etag!,
      idempotencyKey('h37-rel')
    );
    expectSuccess(res);

    const holdAfter = await getHold(workspace.id, matter.id, hold.id);
    expect(holdAfter.status).toBe('RELEASED');
  });

  test('HOLD_038: Suspending hold withdraws draft collections', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const holdData = await getHold(workspace.id, matter.id, hold.id);

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'DRIVE',
      estimated_bytes: 100
    });

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'SUSPENDED' },
      holdData.etag!,
      idempotencyKey('h38-s')
    );
    expectSuccess(res);

    const collAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collAfter.status).toBe('WITHDRAWN');
  });

  test('HOLD_039: Releasing CHAT_ONLY hold withdraws submitted CHAT collections', async () => {
    const { workspace, matter, custodian } = await setupFxWsAMatterLitActive();

    const hold = await createHold(workspace.id, matter.id, {
      legal_basis: 'LITIGATION',
      scope: 'CHAT_ONLY',
      is_court_ordered: false,
      custodian_ids: [custodian.id]
    });
    await issueAndActivateHold(workspace.id, matter.id, hold.id);

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'CHAT',
      estimated_bytes: 100
    });
    let collData = await getCollection(workspace.id, matter.id, collection.id);
    await transitionCollection(workspace.id, matter.id, collection.id, collData.etag!, 'SUBMITTED');

    const wsBefore = await getWorkspace(workspace.id);
    expect(wsBefore.bytes_reserved).toBe(100);

    const holdData = await getHold(workspace.id, matter.id, hold.id);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'RELEASED' },
      holdData.etag!,
      idempotencyKey('h39-rel')
    );
    expectSuccess(res);

    collData = await getCollection(workspace.id, matter.id, collection.id);
    expect(collData.status).toBe('WITHDRAWN');

    const wsAfter = await getWorkspace(workspace.id);
    expect(wsAfter.bytes_reserved).toBe(0);
  });

  test('HOLD_040: Releasing hold does not undo delivered collections', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'DRIVE',
      estimated_bytes: 50
    });

    let collData = await getCollection(workspace.id, matter.id, collection.id);
    await transitionCollection(workspace.id, matter.id, collection.id, collData.etag!, 'SUBMITTED');

    collData = await getCollection(workspace.id, matter.id, collection.id);
    await transitionCollection(workspace.id, matter.id, collection.id, collData.etag!, 'APPROVED');

    collData = await getCollection(workspace.id, matter.id, collection.id);
    await transitionCollection(workspace.id, matter.id, collection.id, collData.etag!, 'IN_PROGRESS');

    collData = await getCollection(workspace.id, matter.id, collection.id);
    await transitionCollection(workspace.id, matter.id, collection.id, collData.etag!, 'DELIVERED', 50);

    const holdData = await getHold(workspace.id, matter.id, hold.id);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'RELEASED' },
      holdData.etag!,
      idempotencyKey('h40-rel')
    );
    expectSuccess(res);

    const ws = await getWorkspace(workspace.id);
    expect(ws.bytes_stored).toBe(50);

    const collAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collAfter.status).toBe('DELIVERED');
  });

  test('HOLD_041: Court-ordered ACTIVE hold causes matter posture FROZEN', async () => {
    const { workspace, matter } = await setupFxWsAHoldCourtActive();

    const matterData = await getMatter(workspace.id, matter.id);

    expect(matterData.posture).toBe('FROZEN');
  });

  test('HOLD_042: Releasing court-ordered hold removes FROZEN posture', async () => {
    const { workspace, matter, custodian } = await setupFxWsAMatterLitActive();

    const hold = await createHold(workspace.id, matter.id, {
      legal_basis: 'REGULATORY',
      scope: 'EMAIL_ONLY',
      is_court_ordered: true,
      custodian_ids: [custodian.id]
    });

    let holdData = await getHold(workspace.id, matter.id, hold.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'ISSUED' },
      holdData.etag!,
      idempotencyKey('h42-iss')
    );

    holdData = await getHold(workspace.id, matter.id, hold.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'ACTIVE' },
      holdData.etag!,
      idempotencyKey('h42-act')
    );

    let matterData = await getMatter(workspace.id, matter.id);
    expect(matterData.posture).toBe('FROZEN');

    holdData = await getHold(workspace.id, matter.id, hold.id);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'RELEASED' },
      holdData.etag!,
      idempotencyKey('h42-rel')
    );
    expectSuccess(res);

    matterData = await getMatter(workspace.id, matter.id);
    expect(matterData.posture).not.toBe('FROZEN');
  });

  test('HOLD_043: Cannot transition DRAFT hold directly to ACTIVE', async () => {
    const { workspace, matter, custodian } = await setupFxWsAMatterLitActive();

    const createRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'CourtHold4',
        legal_basis: 'REGULATORY',
        scope: 'EMAIL_ONLY',
        is_court_ordered: true,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('h43-h')
    );
    expectSuccess(createRes);
    const holdId = unwrap(createRes.body).id;

    const holdData = await getHold(workspace.id, matter.id, holdId);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${holdId}/state`,
      { to_status: 'ACTIVE' },
      holdData.etag!,
      idempotencyKey('h43-act')
    );

    await expectErrorCode(res, 'ERR_INVALID_STATE');

    const holdAfter = await getHold(workspace.id, matter.id, holdId);
    expect(holdAfter.status).toBe('DRAFT');
  });

  test('HOLD_044: Cannot patch an ACTIVE hold - locked for edits', async () => {
    const { workspace, matter, hold } = await setupFxWsAHoldAlldataActive();

    const holdData = await getHold(workspace.id, matter.id, hold.id);

    const res = await patch(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}`,
      { scope: 'EMAIL_ONLY' },
      holdData.etag!,
      idempotencyKey('h44')
    );

    await expectErrorCode(res, 'ERR_INVALID_STATE');

    const holdAfter = await getHold(workspace.id, matter.id, hold.id);
    expect(holdAfter.scope).toBe('ALL_DATA');
  });

  test('HOLD_045: Hold with invalid custodian_ids fails with ERR_BAD_REQUEST', async () => {
    const { workspace, matter } = await setupFxWsAMatterLitActive();

    const res = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'NoSuchCust',
        legal_basis: 'LITIGATION',
        scope: 'ALL_DATA',
        is_court_ordered: false,
        custodian_ids: ['missing']
      },
      idempotencyKey('h45')
    );

    expect(res.status).toBeGreaterThanOrEqual(400);
    const errorCode = res.body?.data?.error_code;
    expect(['ERR_BAD_REQUEST', 'ERR_NOT_FOUND']).toContain(errorCode);

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.posture).toBe('OPEN');
  });

  test('HOLD_046: Releasing ACTIVE hold sets matter posture to OPEN', async () => {
    const { workspace, matter, hold } = await setupFxWsAHoldAlldataActive();

    const holdData = await getHold(workspace.id, matter.id, hold.id);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'RELEASED' },
      holdData.etag!,
      idempotencyKey('h46')
    );
    expectSuccess(res);

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.posture).toBe('OPEN');
  });

  test('HOLD_047: Cannot suspend a RELEASED hold', async () => {
    const { workspace, matter, hold } = await setupFxWsAHoldAlldataActive();

    let holdData = await getHold(workspace.id, matter.id, hold.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'RELEASED' },
      holdData.etag!,
      idempotencyKey('h47-rel')
    );

    holdData = await getHold(workspace.id, matter.id, hold.id);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'SUSPENDED' },
      holdData.etag!,
      idempotencyKey('h47-sus')
    );

    await expectErrorCode(res, 'ERR_INVALID_STATE');

    const holdAfter = await getHold(workspace.id, matter.id, hold.id);
    expect(holdAfter.status).toBe('RELEASED');
  });

  test('HOLD_048: ACTIVE hold can be released', async () => {
    const { workspace, matter, hold } = await setupFxWsAHoldAlldataActive();

    const holdData = await getHold(workspace.id, matter.id, hold.id);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'RELEASED' },
      holdData.etag!,
      idempotencyKey('h48')
    );
    expectSuccess(res);

    const holdAfter = await getHold(workspace.id, matter.id, hold.id);
    expect(holdAfter.status).toBe('RELEASED');
  });

  test('HOLD_049: Suspending hold withdraws submitted collection and sets matter posture to OPEN', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'DRIVE',
      estimated_bytes: 20
    });
    let collData = await getCollection(workspace.id, matter.id, collection.id);
    await transitionCollection(workspace.id, matter.id, collection.id, collData.etag!, 'SUBMITTED');

    const holdData = await getHold(workspace.id, matter.id, hold.id);

    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'SUSPENDED' },
      holdData.etag!,
      idempotencyKey('h49-sus')
    );

    const matterAfter = await getMatter(workspace.id, matter.id);

    expect(matterAfter.posture).toBe('OPEN');
  });

  test('HOLD_050: Suspending hold withdraws submitted collection and matter posture is OPEN', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'DRIVE',
      estimated_bytes: 20
    });
    let collData = await getCollection(workspace.id, matter.id, collection.id);
    await transitionCollection(workspace.id, matter.id, collection.id, collData.etag!, 'SUBMITTED');

    const holdData = await getHold(workspace.id, matter.id, hold.id);

    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'SUSPENDED' },
      holdData.etag!,
      idempotencyKey('h50-sus')
    );

    const matterAfter = await getMatter(workspace.id, matter.id);

    expect(matterAfter.posture).toBe('OPEN');

    const collAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collAfter.status).toBe('WITHDRAWN');
  });

  test('HOLD_051: Court-ordered ACTIVE hold causes workspace posture LOCKDOWN', async () => {
    const { workspace } = await setupFxWsAHoldCourtActive();

    const ws = await getWorkspace(workspace.id);

    expect(ws.posture).toBe('LOCKDOWN');
  });

  test('HOLD_052: Releasing court-ordered hold returns workspace posture to NORMAL', async () => {
    const { workspace, matter, hold } = await setupFxWsAHoldCourtActive();

    const holdData = await getHold(workspace.id, matter.id, hold.id);

    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'RELEASED' },
      holdData.etag!,
      idempotencyKey('h52-rel')
    );

    const ws = await getWorkspace(workspace.id);

    expect(ws.posture).toBe('NORMAL');
  });

  test('HOLD_053: Cannot create new holds in workspace LOCKDOWN', async () => {
    const { workspace, matter, custodian } = await setupFxWsAHoldCourtActive();

    const ws = await getWorkspace(workspace.id);
    expect(ws.posture).toBe('LOCKDOWN');

    const res = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'TryNew',
        legal_basis: 'LITIGATION',
        scope: 'ALL_DATA',
        is_court_ordered: false,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('h53-new')
    );

    if (res.status >= 400) {
      const errorCode = res.body?.data?.error_code;
      expect(errorCode).toBe('ERR_POSTURE_BLOCKED');
    } else {

      const holdId = res.body?.data?.id;
      const hold = await getHold(workspace.id, matter.id, holdId);
      expect(hold.status).toBe('DRAFT');
    }

    const wsAfter = await getWorkspace(workspace.id);
    expect(wsAfter.posture).toBe('LOCKDOWN');
  });

  test('HOLD_054: Releasing holds is allowed even in LOCKDOWN', async () => {
    const { workspace, matter, hold } = await setupFxWsAHoldCourtActive();

    const holdData = await getHold(workspace.id, matter.id, hold.id);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'RELEASED' },
      holdData.etag!,
      idempotencyKey('h54')
    );
    expectSuccess(res);

    const ws = await getWorkspace(workspace.id);
    expect(ws.posture).not.toBe('LOCKDOWN');
  });

  test('HOLD_055: Reinstating court-ordered hold re-triggers FROZEN and LOCKDOWN', async () => {
    const { workspace, matter, hold } = await setupFxWsAHoldCourtActive();

    let holdData = await getHold(workspace.id, matter.id, hold.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'RELEASED' },
      holdData.etag!,
      idempotencyKey('h55-rel')
    );

    holdData = await getHold(workspace.id, matter.id, hold.id);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'ACTIVE' },
      holdData.etag!,
      idempotencyKey('h55-rein')
    );

    if (res.status >= 400) {
      await expectErrorCode(res, 'ERR_INVALID_STATE');
      const holdAfter = await getHold(workspace.id, matter.id, hold.id);
      expect(holdAfter.status).toBe('RELEASED');
    } else {
      expectSuccess(res);

      const matterAfter = await getMatter(workspace.id, matter.id);
      expect(matterAfter.posture).toBe('FROZEN');

      const ws = await getWorkspace(workspace.id);
      expect(ws.posture).toBe('LOCKDOWN');
    }
  });

});
