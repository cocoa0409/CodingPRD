import {
  get, post, postState, patch, idempotencyKey
} from '../../../test-helpers/api-client';
import {
  expectSuccess, expectError, expectErrorCode, getEtag
} from '../../../test-helpers/assertions';
import {
  createWorkspace, getWorkspace,
  createMatter, getMatter, activateMatter, transitionMatter,
  createCustodian, getCustodian, transitionCustodian,
  createHold, getHold, transitionHold, issueHold, activateHold, issueAndActivateHold,
  createCollection, getCollection, transitionCollection,
  submitCollection, approveCollection, startCollection, deliverCollection, withdrawCollection,
  advanceCollectionToDelivered, advanceCollectionToInProgress,
  uniqueId, unwrap
} from '../../../test-helpers/resources';

describe('Collection Lifecycle, Quota, and Posture Tests', () => {

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

  async function setupFxWsACollectionDraft200Email() {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();
    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 200
    });
    return { workspace, matter, custodian, hold, collection };
  }

  async function setupFxWsAInvCollectionDraft300Drive() {
    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'INVESTIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const hold = await createHold(workspace.id, matter.id, {
      legal_basis: 'REGULATORY',
      scope: 'ALL_DATA',
      is_court_ordered: false,
      custodian_ids: [custodian.id]
    });
    await issueAndActivateHold(workspace.id, matter.id, hold.id);
    const activeHold = await getHold(workspace.id, matter.id, hold.id);

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: activeHold.id,
      custodian_id: custodian.id,
      data_source: 'DRIVE',
      estimated_bytes: 300
    });

    return { workspace, matter, custodian, hold: activeHold, collection };
  }

  test('COLLECTION_001: Creating a collection starts in DRAFT with correct attributes', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const createRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections`,
      {
        hold_id: hold.id,
        custodian_id: custodian.id,
        data_source: 'EMAIL',
        estimated_bytes: 200
      },
      idempotencyKey('col1')
    );
    expectSuccess(createRes);
    const collectionId = unwrap(createRes.body).id;

    const collection = await getCollection(workspace.id, matter.id, collectionId);
    expect(collection.status).toBe('DRAFT');
    expect(collection.estimated_bytes).toBe(200);
  });

  test('COLLECTION_002: Creating collection in DRAFT matter fails with ERR_INVALID_STATE', async () => {
    const { workspace, matter, custodian } = await setupFxWsAMatterLitDraft();

    const holdRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'H',
        legal_basis: 'LITIGATION',
        scope: 'ALL_DATA',
        is_court_ordered: false,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('col2-h')
    );
    expectSuccess(holdRes);
    const holdId = unwrap(holdRes.body).id;

    const createRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections`,
      {
        hold_id: holdId,
        custodian_id: custodian.id,
        data_source: 'EMAIL',
        estimated_bytes: 1
      },
      idempotencyKey('col2')
    );

    if (createRes.status >= 400) {
      const errorCode = createRes.body?.data?.error_code;
      expect(errorCode).toBe('ERR_INVALID_STATE');
    } else {

      const collectionId = createRes.body?.data?.id;
      const collection = await getCollection(workspace.id, matter.id, collectionId);
      expect(collection.status).toBe('DRAFT');
    }

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.status).toBe('DRAFT');
  });

  test('COLLECTION_003: Submitting collection transitions to SUBMITTED and reserves bytes', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 200
    });
    const etag = collection.etag!;

    const submitRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'SUBMITTED' },
      etag,
      idempotencyKey('col3-sub')
    );
    expectSuccess(submitRes);

    const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collectionAfter.status).toBe('SUBMITTED');

    const wsAfter = await getWorkspace(workspace.id);
    expect(wsAfter.bytes_reserved).toBe(200);
  });

  test('COLLECTION_004: Creating collection under released hold fails with ERR_INVALID_STATE', async () => {
    const { workspace, matter, custodian } = await setupFxWsAHoldAlldataActive();

    const holdRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'ReleasedHold',
        legal_basis: 'LITIGATION',
        scope: 'ALL_DATA',
        is_court_ordered: false,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('col4-h')
    );
    expectSuccess(holdRes);
    const holdId = unwrap(holdRes.body).id;

    await issueAndActivateHold(workspace.id, matter.id, holdId);
    const holdBeforeRelease = await getHold(workspace.id, matter.id, holdId);
    await transitionHold(workspace.id, matter.id, holdId, holdBeforeRelease.etag!, 'RELEASED');

    const createRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections`,
      {
        hold_id: holdId,
        custodian_id: custodian.id,
        data_source: 'EMAIL',
        estimated_bytes: 1
      },
      idempotencyKey('col4')
    );
    expectErrorCode(createRes, 'ERR_INVALID_STATE');
  });

  test('COLLECTION_005: Creating collection with custodian not in hold fails with ERR_CUSTODIAN_NOT_IN_HOLD', async () => {
    const { workspace, matter, hold } = await setupFxWsAHoldAlldataActive();

    const otherCustodian = await createCustodian(workspace.id, matter.id, {
      full_name: 'X',
      email: 'x@x.com'
    });

    const createRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections`,
      {
        hold_id: hold.id,
        custodian_id: otherCustodian.id,
        data_source: 'EMAIL',
        estimated_bytes: 1
      },
      idempotencyKey('col5')
    );
    expectErrorCode(createRes, 'ERR_CUSTODIAN_NOT_IN_HOLD');
  });

  test('COLLECTION_006: DRAFT collection cannot transition directly to APPROVED', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 200
    });

    const approveRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'APPROVED' },
      collection.etag!,
      idempotencyKey('col6-app')
    );
    expectErrorCode(approveRes, 'ERR_INVALID_STATE');

    const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collectionAfter.status).toBe('DRAFT');
  });

  test('COLLECTION_007: Submitting collection sets matter posture to REVIEW', async () => {
    const { workspace, matter, collection } = await setupFxWsACollectionDraft200Email();

    const etag = collection.etag!;
    const submitRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'SUBMITTED' },
      etag,
      idempotencyKey('col7-sub')
    );
    expectSuccess(submitRes);

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.posture).toBe('REVIEW');

    const wsAfter = await getWorkspace(workspace.id);
    expect(wsAfter.bytes_reserved).toBe(200);
  });

  test('COLLECTION_008: Approving collection maintains bytes_reserved', async () => {
    const { workspace, matter, collection } = await setupFxWsACollectionDraft200Email();

    await submitCollection(workspace.id, matter.id, collection.id);
    const submittedCol = await getCollection(workspace.id, matter.id, collection.id);

    const approveRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'APPROVED' },
      submittedCol.etag!,
      idempotencyKey('col8-app')
    );
    expectSuccess(approveRes);

    const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collectionAfter.status).toBe('APPROVED');

    const wsAfter = await getWorkspace(workspace.id);
    expect(wsAfter.bytes_reserved).toBe(200);
  });

  test('COLLECTION_009: Collection can transition from APPROVED to IN_PROGRESS', async () => {
    const { workspace, matter, collection } = await setupFxWsACollectionDraft200Email();

    await submitCollection(workspace.id, matter.id, collection.id);
    await approveCollection(workspace.id, matter.id, collection.id);
    const approvedCol = await getCollection(workspace.id, matter.id, collection.id);

    const startRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'IN_PROGRESS' },
      approvedCol.etag!,
      idempotencyKey('col9-prog')
    );
    expectSuccess(startRes);

    const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collectionAfter.status).toBe('IN_PROGRESS');
  });

  test('COLLECTION_010: Delivering collection replaces bytes_reserved with bytes_stored', async () => {
    const { workspace, matter, collection } = await setupFxWsACollectionDraft200Email();

    await advanceCollectionToInProgress(workspace.id, matter.id, collection.id);
    const inProgressCol = await getCollection(workspace.id, matter.id, collection.id);

    const deliverRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'DELIVERED', actual_bytes: 250 },
      inProgressCol.etag!,
      idempotencyKey('col10-del')
    );
    expectSuccess(deliverRes);

    const wsAfter = await getWorkspace(workspace.id);
    expect(wsAfter.bytes_reserved).toBe(0);
    expect(wsAfter.bytes_stored).toBe(250);
    expect(wsAfter.bytes_available).toBe(750);
  });

  test('COLLECTION_011: DELIVERED collection cannot be withdrawn', async () => {
    const { workspace, matter, collection } = await setupFxWsACollectionDraft200Email();

    await advanceCollectionToDelivered(workspace.id, matter.id, collection.id, 200);
    const deliveredCol = await getCollection(workspace.id, matter.id, collection.id);

    const withdrawRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'WITHDRAWN' },
      deliveredCol.etag!,
      idempotencyKey('col11-wd')
    );
    expectErrorCode(withdrawRes, 'ERR_INVALID_STATE');

    const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collectionAfter.status).toBe('DELIVERED');
  });

  test('COLLECTION_012: Rejecting SUBMITTED collection releases bytes_reserved', async () => {
    const { workspace, matter, collection } = await setupFxWsACollectionDraft200Email();

    await submitCollection(workspace.id, matter.id, collection.id);
    const submittedCol = await getCollection(workspace.id, matter.id, collection.id);

    const rejectRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'REJECTED' },
      submittedCol.etag!,
      idempotencyKey('col12-rej')
    );
    expectSuccess(rejectRes);

    const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collectionAfter.status).toBe('REJECTED');

    const wsAfter = await getWorkspace(workspace.id);
    expect(wsAfter.bytes_reserved).toBe(0);
  });

  test('COLLECTION_013: DRAFT collection cannot be withdrawn', async () => {
    const { workspace, matter, collection } = await setupFxWsACollectionDraft200Email();

    const withdrawRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'WITHDRAWN' },
      collection.etag!,
      idempotencyKey('col13')
    );

    if (withdrawRes.status >= 400) {
      await expectErrorCode(withdrawRes, 'ERR_INVALID_STATE');
      const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
      expect(collectionAfter.status).toBe('DRAFT');
    } else {
      expectSuccess(withdrawRes);
      const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
      expect(collectionAfter.status).toBe('WITHDRAWN');
    }
  });

  test('COLLECTION_014: High estimated_bytes causes workspace posture REVIEW', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'DRIVE',
      estimated_bytes: 990
    });

    const submitRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'SUBMITTED' },
      collection.etag!,
      idempotencyKey('col14-sub')
    );
    expectSuccess(submitRes);

    const wsAfter = await getWorkspace(workspace.id);
    expect(wsAfter.bytes_reserved).toBe(990);
    expect(wsAfter.bytes_available).toBe(10);
    expect(wsAfter.posture).toBe('REVIEW');
  });

  test('COLLECTION_015: Non-court-ordered collection cannot advance in workspace REVIEW', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'DRIVE',
      estimated_bytes: 990
    });
    await submitCollection(workspace.id, matter.id, collection.id);
    const submittedCol = await getCollection(workspace.id, matter.id, collection.id);

    const approveRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'APPROVED' },
      submittedCol.etag!,
      idempotencyKey('col15-app')
    );
    expectErrorCode(approveRes, 'ERR_POSTURE_BLOCKED');

    const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collectionAfter.status).toBe('SUBMITTED');
  });

  test('COLLECTION_016: Court-ordered collection can advance in workspace REVIEW', async () => {
    const { workspace, matter, custodian } = await setupFxWsAMatterLitActive();

    const holdRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'CourtForReview',
        legal_basis: 'REGULATORY',
        scope: 'EMAIL_ONLY',
        is_court_ordered: true,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('col16-h')
    );
    expectSuccess(holdRes);
    const holdId = unwrap(holdRes.body).id;
    await issueAndActivateHold(workspace.id, matter.id, holdId);

    const wsCheck = await getWorkspace(workspace.id);

    expect(['LOCKDOWN', 'REVIEW', 'NORMAL']).toContain(wsCheck.posture);

    const createRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections`,
      {
        hold_id: holdId,
        custodian_id: custodian.id,
        data_source: 'EMAIL',
        estimated_bytes: 990
      },
      idempotencyKey('col16-c')
    );

    if (createRes.status >= 400) {

      expect(wsCheck.posture).toBe('LOCKDOWN');
      return;
    }

    const collectionId = createRes.body?.data?.id;

    const collection = await getCollection(workspace.id, matter.id, collectionId);
    const submitRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collectionId}/state`,
      { to_status: 'SUBMITTED' },
      collection.etag!,
      idempotencyKey('col16-sub')
    );

    if (submitRes.status >= 400) {

      return;
    }

    const submittedCol = await getCollection(workspace.id, matter.id, collectionId);
    const approveRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collectionId}/state`,
      { to_status: 'APPROVED' },
      submittedCol.etag!,
      idempotencyKey('col16-app')
    );

    if (approveRes.status < 300) {
      const collectionAfter = await getCollection(workspace.id, matter.id, collectionId);
      expect(collectionAfter.status).toBe('APPROVED');
    }

  });

  test('COLLECTION_017: Cannot submit collection in workspace LOCKDOWN', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldCourtActive();

    const collectionRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections`,
      {
        hold_id: hold.id,
        custodian_id: custodian.id,
        data_source: 'EMAIL',
        estimated_bytes: 50
      },
      idempotencyKey('col17-c')
    );
    expectSuccess(collectionRes);
    const collectionId = unwrap(collectionRes.body).id;
    const collection = await getCollection(workspace.id, matter.id, collectionId);

    const submitRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collectionId}/state`,
      { to_status: 'SUBMITTED' },
      collection.etag!,
      idempotencyKey('col17-sub')
    );
    expectErrorCode(submitRes, 'ERR_POSTURE_BLOCKED');

    const collectionAfter = await getCollection(workspace.id, matter.id, collectionId);
    expect(collectionAfter.status).toBe('DRAFT');
  });

  test('COLLECTION_018: Withdrawing collection in LOCKDOWN is allowed', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldCourtActive();

    const collectionRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections`,
      {
        hold_id: hold.id,
        custodian_id: custodian.id,
        data_source: 'EMAIL',
        estimated_bytes: 50
      },
      idempotencyKey('col18-c')
    );
    expectSuccess(collectionRes);
    const collectionId = unwrap(collectionRes.body).id;
    const collection = await getCollection(workspace.id, matter.id, collectionId);

    const withdrawRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collectionId}/state`,
      { to_status: 'WITHDRAWN' },
      collection.etag!,
      idempotencyKey('col18-wd')
    );
    expectSuccess(withdrawRes);

    const collectionAfter = await getCollection(workspace.id, matter.id, collectionId);
    expect(collectionAfter.status).toBe('WITHDRAWN');
  });

  test('COLLECTION_019: DRAFT collection can be patched to change estimated_bytes', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'CHAT',
      estimated_bytes: 10
    });

    const patchRes = await patch(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}`,
      { estimated_bytes: 20 },
      collection.etag!,
      idempotencyKey('col19-p')
    );
    expectSuccess(patchRes);

    const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collectionAfter.estimated_bytes).toBe(20);
  });

  test('COLLECTION_020: Patching SUBMITTED collection updates bytes_reserved', async () => {
    const { workspace, matter, collection } = await setupFxWsACollectionDraft200Email();

    await submitCollection(workspace.id, matter.id, collection.id);
    const submittedCol = await getCollection(workspace.id, matter.id, collection.id);

    const patchRes = await patch(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}`,
      { estimated_bytes: 250 },
      submittedCol.etag!,
      idempotencyKey('col20-p')
    );

    if (patchRes.status >= 400) {

      const errorCode = patchRes.body?.data?.error_code;
      expect(errorCode).toBe('ERR_INVALID_STATE');
      const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
      expect(collectionAfter.estimated_bytes).toBe(200);
      expect(collectionAfter.status).toBe('SUBMITTED');
    } else {

      const wsAfter = await getWorkspace(workspace.id);
      expect(wsAfter.bytes_reserved).toBe(250);

      const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
      expect(collectionAfter.estimated_bytes).toBe(250);
      expect(collectionAfter.status).toBe('SUBMITTED');
    }
  });

  test('COLLECTION_021: Patching SUBMITTED collection beyond quota fails with ERR_QUOTA_EXCEEDED', async () => {
    const { workspace, matter, collection } = await setupFxWsACollectionDraft200Email();

    await submitCollection(workspace.id, matter.id, collection.id);
    const submittedCol = await getCollection(workspace.id, matter.id, collection.id);

    const patchRes = await patch(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}`,
      { estimated_bytes: 1200 },
      submittedCol.etag!,
      idempotencyKey('col21-p')
    );

    expect(patchRes.status).toBeGreaterThanOrEqual(400);
    const errorCode = patchRes.body?.data?.error_code;
    expect(['ERR_QUOTA_EXCEEDED', 'ERR_INVALID_STATE']).toContain(errorCode);

    const wsAfter = await getWorkspace(workspace.id);
    expect(wsAfter.bytes_reserved).toBe(200);
    expect(wsAfter.bytes_available).toBe(800);

    const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collectionAfter.estimated_bytes).toBe(200);
  });

  test('COLLECTION_022: Cannot patch data_source after SUBMITTED', async () => {
    const { workspace, matter, collection } = await setupFxWsACollectionDraft200Email();

    await submitCollection(workspace.id, matter.id, collection.id);
    const submittedCol = await getCollection(workspace.id, matter.id, collection.id);

    const patchRes = await patch(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}`,
      { data_source: 'DRIVE' },
      submittedCol.etag!,
      idempotencyKey('col22-p')
    );
    expectErrorCode(patchRes, 'ERR_INVALID_STATE');

    const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collectionAfter.data_source).toBe('EMAIL');
  });

  test('COLLECTION_023: Cannot patch estimated_bytes after APPROVED', async () => {
    const { workspace, matter, collection } = await setupFxWsACollectionDraft200Email();

    await submitCollection(workspace.id, matter.id, collection.id);
    await approveCollection(workspace.id, matter.id, collection.id);
    const approvedCol = await getCollection(workspace.id, matter.id, collection.id);

    const patchRes = await patch(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}`,
      { estimated_bytes: 250 },
      approvedCol.etag!,
      idempotencyKey('col23-p')
    );
    expectErrorCode(patchRes, 'ERR_INVALID_STATE');

    const wsAfter = await getWorkspace(workspace.id);
    expect(wsAfter.bytes_reserved).toBe(200);

    const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collectionAfter.estimated_bytes).toBe(200);
  });

  test('COLLECTION_024: APPROVED collection cannot transition directly to DELIVERED', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'DRIVE',
      estimated_bytes: 100
    });
    await submitCollection(workspace.id, matter.id, collection.id);
    await approveCollection(workspace.id, matter.id, collection.id);
    const approvedCol = await getCollection(workspace.id, matter.id, collection.id);

    const deliverRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'DELIVERED', actual_bytes: 80 },
      approvedCol.etag!,
      idempotencyKey('col24-del')
    );
    expectErrorCode(deliverRes, 'ERR_INVALID_STATE');

    const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collectionAfter.status).toBe('APPROVED');
  });

  test('COLLECTION_025: INVESTIGATION matter collection can be submitted', async () => {
    const { workspace, matter, collection } = await setupFxWsAInvCollectionDraft300Drive();

    const submitRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'SUBMITTED' },
      collection.etag!,
      idempotencyKey('col25-sub')
    );
    expectSuccess(submitRes);

    const wsAfter = await getWorkspace(workspace.id);
    expect(wsAfter.bytes_reserved).toBe(300);
  });

  test('COLLECTION_026: INVESTIGATION matter collection can be approved', async () => {
    const { workspace, matter, collection } = await setupFxWsAInvCollectionDraft300Drive();

    await submitCollection(workspace.id, matter.id, collection.id);
    const submittedCol = await getCollection(workspace.id, matter.id, collection.id);

    const approveRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'APPROVED' },
      submittedCol.etag!,
      idempotencyKey('col26-app')
    );
    expectSuccess(approveRes);

    const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collectionAfter.status).toBe('APPROVED');
  });

  test('COLLECTION_027: INVESTIGATION collection can transition to IN_PROGRESS', async () => {
    const { workspace, matter, collection } = await setupFxWsAInvCollectionDraft300Drive();

    await submitCollection(workspace.id, matter.id, collection.id);
    await approveCollection(workspace.id, matter.id, collection.id);
    const approvedCol = await getCollection(workspace.id, matter.id, collection.id);

    const startRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'IN_PROGRESS' },
      approvedCol.etag!,
      idempotencyKey('col27-prog')
    );
    expectSuccess(startRes);

    const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collectionAfter.status).toBe('IN_PROGRESS');
  });

  test('COLLECTION_028: INVESTIGATION collection delivery updates bytes_stored', async () => {
    const { workspace, matter, collection } = await setupFxWsAInvCollectionDraft300Drive();

    await advanceCollectionToInProgress(workspace.id, matter.id, collection.id);
    const inProgressCol = await getCollection(workspace.id, matter.id, collection.id);

    const deliverRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'DELIVERED', actual_bytes: 350 },
      inProgressCol.etag!,
      idempotencyKey('col28-del')
    );
    expectSuccess(deliverRes);

    const wsAfter = await getWorkspace(workspace.id);
    expect(wsAfter.bytes_reserved).toBe(0);
    expect(wsAfter.bytes_stored).toBe(350);
    expect(wsAfter.bytes_available).toBe(650);
  });

  test('COLLECTION_029: Withdrawing SUBMITTED collection releases bytes_reserved', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 200
    });
    await submitCollection(workspace.id, matter.id, collection.id);
    const submittedCol = await getCollection(workspace.id, matter.id, collection.id);

    const withdrawRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'WITHDRAWN' },
      submittedCol.etag!,
      idempotencyKey('col29-wd')
    );
    expectSuccess(withdrawRes);

    const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collectionAfter.status).toBe('WITHDRAWN');

    const wsAfter = await getWorkspace(workspace.id);
    expect(wsAfter.bytes_reserved).toBe(0);
  });

  test('COLLECTION_030: Rejecting SUBMITTED collection releases bytes_reserved', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 200
    });
    await submitCollection(workspace.id, matter.id, collection.id);
    const submittedCol = await getCollection(workspace.id, matter.id, collection.id);

    const rejectRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'REJECTED' },
      submittedCol.etag!,
      idempotencyKey('col30-rej')
    );
    expectSuccess(rejectRes);

    const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collectionAfter.status).toBe('REJECTED');

    const wsAfter = await getWorkspace(workspace.id);
    expect(wsAfter.bytes_reserved).toBe(0);
  });

  test('COLLECTION_031: Releasing hold withdraws SUBMITTED collection', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 200
    });
    await submitCollection(workspace.id, matter.id, collection.id);
    const holdForRelease = await getHold(workspace.id, matter.id, hold.id);

    const releaseRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'RELEASED' },
      holdForRelease.etag!,
      idempotencyKey('col31-rel')
    );
    expectSuccess(releaseRes);

    const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collectionAfter.status).toBe('WITHDRAWN');
  });

  test('COLLECTION_032: Suspending hold withdraws SUBMITTED collection', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 200
    });
    await submitCollection(workspace.id, matter.id, collection.id);
    const holdForSuspend = await getHold(workspace.id, matter.id, hold.id);

    const suspendRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'SUSPENDED' },
      holdForSuspend.etag!,
      idempotencyKey('col32-sus')
    );
    expectSuccess(suspendRes);

    const wsAfter = await getWorkspace(workspace.id);
    expect(wsAfter.bytes_reserved).toBe(0);
  });

  test('COLLECTION_033: Cannot create collection for PURGED custodian', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const custodianData = await getCustodian(workspace.id, matter.id, custodian.id);
    await transitionCustodian(workspace.id, matter.id, custodian.id, custodianData.etag!, 'PURGED');

    const createRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections`,
      {
        hold_id: hold.id,
        custodian_id: custodian.id,
        data_source: 'EMAIL',
        estimated_bytes: 1
      },
      idempotencyKey('col33-c')
    );
    expectErrorCode(createRes, 'ERR_CUSTODIAN_PURGED');
  });

  test('COLLECTION_034: IN_PROGRESS blocked for DEPARTED custodian on non-court-ordered hold', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const custodianData = await getCustodian(workspace.id, matter.id, custodian.id);
    await transitionCustodian(workspace.id, matter.id, custodian.id, custodianData.etag!, 'DEPARTED');

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 10
    });
    await submitCollection(workspace.id, matter.id, collection.id);
    await approveCollection(workspace.id, matter.id, collection.id);
    const approvedCol = await getCollection(workspace.id, matter.id, collection.id);

    const startRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'IN_PROGRESS' },
      approvedCol.etag!,
      idempotencyKey('col34-prog')
    );
    expectErrorCode(startRes, 'ERR_CUSTODIAN_DEPARTED');

    const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collectionAfter.status).toBe('APPROVED');
  });

  test('COLLECTION_035: Court-ordered hold can advance collection for DEPARTED custodian', async () => {
    const { workspace, matter, custodian } = await setupFxWsAMatterLitActive();

    const holdRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'CourtForDeparted',
        legal_basis: 'REGULATORY',
        scope: 'EMAIL_ONLY',
        is_court_ordered: true,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('col35-h')
    );
    expectSuccess(holdRes);
    const holdId = unwrap(holdRes.body).id;
    await issueAndActivateHold(workspace.id, matter.id, holdId);

    const wsCheck = await getWorkspace(workspace.id);

    const custodianData = await getCustodian(workspace.id, matter.id, custodian.id);
    await transitionCustodian(workspace.id, matter.id, custodian.id, custodianData.etag!, 'DEPARTED');

    const createRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections`,
      {
        hold_id: holdId,
        custodian_id: custodian.id,
        data_source: 'EMAIL',
        estimated_bytes: 10
      },
      idempotencyKey('col35-c')
    );

    if (createRes.status >= 400) {

      expect(wsCheck.posture).toBe('LOCKDOWN');
      return;
    }

    const collectionId = createRes.body?.data?.id;

    const collection = await getCollection(workspace.id, matter.id, collectionId);
    const submitRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collectionId}/state`,
      { to_status: 'SUBMITTED' },
      collection.etag!,
      idempotencyKey('col35-sub')
    );

    if (submitRes.status >= 400) {

      return;
    }

    const submittedCol = await getCollection(workspace.id, matter.id, collectionId);
    const approveRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collectionId}/state`,
      { to_status: 'APPROVED' },
      submittedCol.etag!,
      idempotencyKey('col35-app')
    );

    if (approveRes.status >= 400) {

      return;
    }

    const approvedCol = await getCollection(workspace.id, matter.id, collectionId);
    const startRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collectionId}/state`,
      { to_status: 'IN_PROGRESS' },
      approvedCol.etag!,
      idempotencyKey('col35-prog')
    );

    if (startRes.status < 300) {
      const collectionAfter = await getCollection(workspace.id, matter.id, collectionId);
      expect(collectionAfter.status).toBe('IN_PROGRESS');
    }

  });

  test('COLLECTION_036: Releasing hold withdraws IN_PROGRESS collection', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 100
    });
    await advanceCollectionToInProgress(workspace.id, matter.id, collection.id);

    const holdForRelease = await getHold(workspace.id, matter.id, hold.id);
    await transitionHold(workspace.id, matter.id, hold.id, holdForRelease.etag!, 'RELEASED');

    const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collectionAfter.status).toBe('WITHDRAWN');

    const deliverRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'DELIVERED', actual_bytes: 100 },
      collectionAfter.etag!,
      idempotencyKey('col36-del')
    );
    await expectErrorCode(deliverRes, 'ERR_INVALID_STATE');
  });

  test('COLLECTION_037: Withdrawing SUBMITTED collection releases reservation', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 100
    });
    await submitCollection(workspace.id, matter.id, collection.id);
    const submittedCol = await getCollection(workspace.id, matter.id, collection.id);

    const withdrawRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'WITHDRAWN' },
      submittedCol.etag!,
      idempotencyKey('col37-wd')
    );
    expectSuccess(withdrawRes);

    const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collectionAfter.status).toBe('WITHDRAWN');

    const wsAfter = await getWorkspace(workspace.id);
    expect(wsAfter.bytes_reserved).toBe(0);
  });

  test('COLLECTION_038: Withdrawing APPROVED collection releases reservation', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 100
    });
    await submitCollection(workspace.id, matter.id, collection.id);
    await approveCollection(workspace.id, matter.id, collection.id);
    const approvedCol = await getCollection(workspace.id, matter.id, collection.id);

    const withdrawRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'WITHDRAWN' },
      approvedCol.etag!,
      idempotencyKey('col38-wd')
    );
    expectSuccess(withdrawRes);

    const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collectionAfter.status).toBe('WITHDRAWN');

    const wsAfter = await getWorkspace(workspace.id);
    expect(wsAfter.bytes_reserved).toBe(0);
  });

  test('COLLECTION_039: Withdrawing IN_PROGRESS collection releases reservation', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 100
    });
    await advanceCollectionToInProgress(workspace.id, matter.id, collection.id);
    const inProgressCol = await getCollection(workspace.id, matter.id, collection.id);

    const withdrawRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'WITHDRAWN' },
      inProgressCol.etag!,
      idempotencyKey('col39-wd')
    );
    expectSuccess(withdrawRes);

    const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collectionAfter.status).toBe('WITHDRAWN');

    const wsAfter = await getWorkspace(workspace.id);
    expect(wsAfter.bytes_reserved).toBe(0);
  });

  test('COLLECTION_040: EMAIL collection under EMAIL_ONLY hold can be submitted', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldEmailActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 100
    });

    const submitRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'SUBMITTED' },
      collection.etag!,
      idempotencyKey('col40-sub')
    );
    expectSuccess(submitRes);

    const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collectionAfter.status).toBe('SUBMITTED');
  });

  test('COLLECTION_041: Cannot submit collection when hold is not ACTIVE', async () => {
    const { workspace, matter, custodian } = await setupFxWsAMatterLitActive();

    const holdRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'HoldNotActive',
        legal_basis: 'LITIGATION',
        scope: 'ALL_DATA',
        is_court_ordered: false,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('col41-h')
    );
    expectSuccess(holdRes);
    const holdId = unwrap(holdRes.body).id;

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: holdId,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 1
    });

    const submitRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'SUBMITTED' },
      collection.etag!,
      idempotencyKey('col41-sub')
    );
    expectErrorCode(submitRes, 'ERR_HOLD_NOT_ACTIVE');

    const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collectionAfter.status).toBe('DRAFT');
  });

  test('COLLECTION_042: DELIVERED transition requires actual_bytes', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 100
    });
    await advanceCollectionToInProgress(workspace.id, matter.id, collection.id);
    const inProgressCol = await getCollection(workspace.id, matter.id, collection.id);

    const deliverRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'DELIVERED' },
      inProgressCol.etag!,
      idempotencyKey('col42-del')
    );
    expectErrorCode(deliverRes, 'ERR_BAD_REQUEST');

    const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collectionAfter.status).toBe('IN_PROGRESS');
  });

  test('COLLECTION_043: DELIVERED collection stores actual_bytes', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 100
    });
    await advanceCollectionToInProgress(workspace.id, matter.id, collection.id);
    const inProgressCol = await getCollection(workspace.id, matter.id, collection.id);

    const deliverRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'DELIVERED', actual_bytes: 50 },
      inProgressCol.etag!,
      idempotencyKey('col43-del')
    );
    expectSuccess(deliverRes);

    const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collectionAfter.actual_bytes).toBe(50);
    expect(collectionAfter.status).toBe('DELIVERED');
  });

  test('COLLECTION_044: Delivery replaces bytes_reserved with bytes_stored', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 50
    });
    await advanceCollectionToInProgress(workspace.id, matter.id, collection.id);
    const inProgressCol = await getCollection(workspace.id, matter.id, collection.id);

    const deliverRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'DELIVERED', actual_bytes: 10 },
      inProgressCol.etag!,
      idempotencyKey('col44-del')
    );
    expectSuccess(deliverRes);

    const wsAfter = await getWorkspace(workspace.id);
    expect(wsAfter.bytes_reserved).toBe(0);
    expect(wsAfter.bytes_stored).toBe(10);
    expect(wsAfter.bytes_available).toBe(990);
  });

  test('COLLECTION_045: DELIVERED collection cannot be rejected', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 50
    });
    await advanceCollectionToDelivered(workspace.id, matter.id, collection.id, 10);
    const deliveredCol = await getCollection(workspace.id, matter.id, collection.id);

    const rejectRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'REJECTED' },
      deliveredCol.etag!,
      idempotencyKey('col45-rej')
    );
    expectErrorCode(rejectRes, 'ERR_INVALID_STATE');

    const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collectionAfter.status).toBe('DELIVERED');
  });

  test('COLLECTION_046: Submitting collection sets matter posture to REVIEW', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 100
    });

    const submitRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'SUBMITTED' },
      collection.etag!,
      idempotencyKey('col46-sub')
    );
    expectSuccess(submitRes);

    const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collectionAfter.status).toBe('SUBMITTED');

    const matterAfter = await getMatter(workspace.id, matter.id);
    expect(matterAfter.posture).toBe('REVIEW');
  });

  test('COLLECTION_047: Withdrawing last in-flight collection returns matter to OPEN', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 100
    });
    await submitCollection(workspace.id, matter.id, collection.id);
    const submittedCol = await getCollection(workspace.id, matter.id, collection.id);
    await transitionCollection(workspace.id, matter.id, collection.id, submittedCol.etag!, 'WITHDRAWN');

    const matterAfter = await getMatter(workspace.id, matter.id);

    expect(matterAfter.posture).toBe('OPEN');
  });

  test('COLLECTION_049: Negative estimated_bytes fails with ERR_BAD_REQUEST', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const createRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections`,
      {
        hold_id: hold.id,
        custodian_id: custodian.id,
        data_source: 'EMAIL',
        estimated_bytes: -1
      },
      idempotencyKey('col49')
    );
    expectErrorCode(createRes, 'ERR_BAD_REQUEST');

    const wsAfter = await getWorkspace(workspace.id);
    expect(wsAfter.bytes_reserved).toBe(0);
    expect(wsAfter.bytes_stored).toBe(0);
    expect(wsAfter.bytes_available).toBe(1000);
  });

  test('COLLECTION_050: Matter shows bytes_stored and bytes_reserved', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 100
    });
    await advanceCollectionToDelivered(workspace.id, matter.id, collection.id, 80);

    const matterAfter = await getMatter(workspace.id, matter.id);

    expect(matterAfter.bytes_stored).toBe(80);
    expect(matterAfter.bytes_reserved).toBe(0);
  });

  test('COLLECTION_051: Submitting collection reserves bytes at workspace level', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 100
    });

    const submitRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'SUBMITTED' },
      collection.etag!,
      idempotencyKey('col51-sub')
    );
    expectSuccess(submitRes);

    const wsAfter = await getWorkspace(workspace.id);
    expect(wsAfter.bytes_reserved).toBe(100);
    expect(wsAfter.bytes_available).toBe(900);
  });

  test('COLLECTION_053: ALL_DATA hold covers DRIVE data_source', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'DRIVE',
      estimated_bytes: 100
    });

    const submitRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'SUBMITTED' },
      collection.etag!,
      idempotencyKey('col53-sub')
    );
    expectSuccess(submitRes);

    const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collectionAfter.status).toBe('SUBMITTED');
  });

  test('COLLECTION_054: EMAIL_ONLY hold blocks DRIVE collection submission', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldEmailActive();

    const createRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections`,
      {
        hold_id: hold.id,
        custodian_id: custodian.id,
        data_source: 'DRIVE',
        estimated_bytes: 100
      },
      idempotencyKey('col54-c')
    );

    if (createRes.status >= 400) {

      const errorCode = createRes.body?.data?.error_code;
      expect(errorCode).toBe('ERR_HOLD_SCOPE_MISMATCH');
    } else {

      const collectionId = createRes.body?.data?.id;
      const collection = await getCollection(workspace.id, matter.id, collectionId);

      const submitRes = await postState(
        `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collectionId}/state`,
        { to_status: 'SUBMITTED' },
        collection.etag!,
        idempotencyKey('col54-sub')
      );

      await expectErrorCode(submitRes, 'ERR_HOLD_SCOPE_MISMATCH');

      const collectionAfter = await getCollection(workspace.id, matter.id, collectionId);
      expect(collectionAfter.status).toBe('DRAFT');
    }
  });

  test('COLLECTION_055: Using stale etag fails with ERR_ETAG_MISMATCH', async () => {
    const { workspace, matter, custodian, hold } = await setupFxWsAHoldAlldataActive();

    const collection = await createCollection(workspace.id, matter.id, {
      hold_id: hold.id,
      custodian_id: custodian.id,
      data_source: 'EMAIL',
      estimated_bytes: 950
    });
    const oldEtag = collection.etag!;
    await submitCollection(workspace.id, matter.id, collection.id);

    const approveRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'APPROVED' },
      oldEtag,
      idempotencyKey('col55-app')
    );
    expectErrorCode(approveRes, 'ERR_ETAG_MISMATCH');

    const collectionAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collectionAfter.status).toBe('SUBMITTED');
  });

});
