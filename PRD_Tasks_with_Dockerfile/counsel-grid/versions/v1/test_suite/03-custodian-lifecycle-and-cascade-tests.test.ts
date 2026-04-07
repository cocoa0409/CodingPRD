import {
  get, post, postState, idempotencyKey
} from '../../../test-helpers/api-client';
import {
  expectSuccess, expectError, expectErrorCode
} from '../../../test-helpers/assertions';
import {
  createWorkspace, getWorkspace,
  createMatter, getMatter, activateMatter,
  createCustodian, getCustodian, transitionCustodian,
  createHold, getHold, issueHold, activateHold, issueAndActivateHold, transitionHold,
  createCollection, getCollection, transitionCollection,
  uniqueId, unwrap
} from '../../../test-helpers/resources';

describe('Custodian Lifecycle and Cascade Tests', () => {

  test('CUSTODIAN_001: Custodian starts with status ACTIVE', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id, {
      full_name: 'Alice A',
      email: 'alice@example.com'
    });
    await activateMatter(workspace.id, matter.id);

    const custodianData = await getCustodian(workspace.id, matter.id, custodian.id);

    expect(custodianData.status).toBe('ACTIVE');
    expect(custodianData.full_name).toBe('Alice A');
  });

  test('CUSTODIAN_002: Transitioning custodian to DEPARTED succeeds', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const custodianData = await getCustodian(workspace.id, matter.id, custodian.id);
    const etag = custodianData.etag!;

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/custodians/${custodian.id}/state`,
      { to_status: 'DEPARTED' },
      etag,
      idempotencyKey('c2')
    );
    expectSuccess(res);

    const custodianAfter = await getCustodian(workspace.id, matter.id, custodian.id);
    expect(custodianAfter.status).toBe('DEPARTED');
  });

  test('CUSTODIAN_003: DEPARTED custodian can be transitioned back to ACTIVE', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    let custodianData = await getCustodian(workspace.id, matter.id, custodian.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/custodians/${custodian.id}/state`,
      { to_status: 'DEPARTED' },
      custodianData.etag!,
      idempotencyKey('c3-d')
    );

    custodianData = await getCustodian(workspace.id, matter.id, custodian.id);
    expect(custodianData.status).toBe('DEPARTED');

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/custodians/${custodian.id}/state`,
      { to_status: 'ACTIVE' },
      custodianData.etag!,
      idempotencyKey('c3-a')
    );
    expectSuccess(res);

    const custodianAfter = await getCustodian(workspace.id, matter.id, custodian.id);
    expect(custodianAfter.status).toBe('ACTIVE');
  });

  test('CUSTODIAN_004: Transitioning custodian to PURGED succeeds', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const custodianData = await getCustodian(workspace.id, matter.id, custodian.id);
    const etag = custodianData.etag!;

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/custodians/${custodian.id}/state`,
      { to_status: 'PURGED' },
      etag,
      idempotencyKey('c4')
    );
    expectSuccess(res);

    const custodianAfter = await getCustodian(workspace.id, matter.id, custodian.id);
    expect(custodianAfter.status).toBe('PURGED');
  });

  test('CUSTODIAN_005: Purging custodian cascades to release hold and withdraw collection', async () => {

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
        data_source: 'EMAIL',
        estimated_bytes: 200
      },
      idempotencyKey('c5-col')
    );
    expectSuccess(collRes);
    const collection = unwrap(collRes.body);

    let collData = await getCollection(workspace.id, matter.id, collection.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'SUBMITTED' },
      collData.etag!,
      idempotencyKey('c5-sub')
    );

    let wsData = await getWorkspace(workspace.id);
    expect(wsData.bytes_reserved).toBe(200);

    const custodianData = await getCustodian(workspace.id, matter.id, custodian.id);

    const purgeRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/custodians/${custodian.id}/state`,
      { to_status: 'PURGED' },
      custodianData.etag!,
      idempotencyKey('c5-purge')
    );
    expectSuccess(purgeRes);

    const holdAfter = await getHold(workspace.id, matter.id, hold.id);
    expect(holdAfter.status).toBe('RELEASED');

    collData = await getCollection(workspace.id, matter.id, collection.id);
    expect(collData.status).toBe('WITHDRAWN');

    wsData = await getWorkspace(workspace.id);
    expect(wsData.bytes_reserved).toBe(0);
  });

  test('CUSTODIAN_006: Purging custodian does not withdraw DELIVERED collections', async () => {

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
        data_source: 'EMAIL',
        estimated_bytes: 200
      },
      idempotencyKey('c6-col')
    );
    expectSuccess(collRes);
    const collection = unwrap(collRes.body);

    let collData = await getCollection(workspace.id, matter.id, collection.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'SUBMITTED' },
      collData.etag!,
      idempotencyKey('c6-sub')
    );

    collData = await getCollection(workspace.id, matter.id, collection.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'APPROVED' },
      collData.etag!,
      idempotencyKey('c6-app')
    );

    collData = await getCollection(workspace.id, matter.id, collection.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'IN_PROGRESS' },
      collData.etag!,
      idempotencyKey('c6-prog')
    );

    collData = await getCollection(workspace.id, matter.id, collection.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'DELIVERED', actual_bytes: 50 },
      collData.etag!,
      idempotencyKey('c6-del')
    );

    collData = await getCollection(workspace.id, matter.id, collection.id);
    expect(collData.status).toBe('DELIVERED');

    let wsData = await getWorkspace(workspace.id);
    expect(wsData.bytes_stored).toBe(50);

    const custodianData = await getCustodian(workspace.id, matter.id, custodian.id);

    const purgeRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/custodians/${custodian.id}/state`,
      { to_status: 'PURGED' },
      custodianData.etag!,
      idempotencyKey('c6-purge')
    );
    expectSuccess(purgeRes);

    collData = await getCollection(workspace.id, matter.id, collection.id);
    expect(collData.status).toBe('DELIVERED');

    wsData = await getWorkspace(workspace.id);
    expect(wsData.bytes_stored).toBe(50);
  });

  test('CUSTODIAN_007: Purging custodian covered by ACTIVE court-ordered hold fails', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);

    const hold = await createHold(workspace.id, matter.id, {
      legal_basis: 'REGULATORY',
      scope: 'EMAIL_ONLY',
      is_court_ordered: true,
      custodian_ids: [custodian.id]
    });
    await issueAndActivateHold(workspace.id, matter.id, hold.id);
    await activateMatter(workspace.id, matter.id);

    const holdData = await getHold(workspace.id, matter.id, hold.id);
    expect(holdData.is_court_ordered).toBe(true);
    expect(holdData.status).toBe('ACTIVE');

    const custodianData = await getCustodian(workspace.id, matter.id, custodian.id);

    const purgeRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/custodians/${custodian.id}/state`,
      { to_status: 'PURGED' },
      custodianData.etag!,
      idempotencyKey('c7')
    );

    await expectErrorCode(purgeRes, 'ERR_COURT_ORDERED_RESTRICTION');

    const custodianAfter = await getCustodian(workspace.id, matter.id, custodian.id);
    expect(custodianAfter.status).not.toBe('PURGED');
  });

  test('CUSTODIAN_008: Issuing non-court-ordered hold to departed custodian fails', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const holdRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'H1',
        legal_basis: 'LITIGATION',
        scope: 'ALL_DATA',
        is_court_ordered: false,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('c8-h')
    );
    expectSuccess(holdRes);
    const hold = unwrap(holdRes.body);

    const holdData = await getHold(workspace.id, matter.id, hold.id);
    const holdEtag = holdData.etag!;

    const custodianData = await getCustodian(workspace.id, matter.id, custodian.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/custodians/${custodian.id}/state`,
      { to_status: 'DEPARTED' },
      custodianData.etag!,
      idempotencyKey('c8-dep')
    );

    const issueRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'ISSUED' },
      holdEtag,
      idempotencyKey('c8-iss')
    );

    await expectErrorCode(issueRes, 'ERR_CUSTODIAN_DEPARTED');

    const holdAfter = await getHold(workspace.id, matter.id, hold.id);
    expect(holdAfter.status).toBe('DRAFT');
  });

  test('CUSTODIAN_009: Issuing court-ordered hold to departed custodian succeeds', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const holdRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'CourtDep',
        legal_basis: 'REGULATORY',
        scope: 'EMAIL_ONLY',
        is_court_ordered: true,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('c9-h')
    );
    expectSuccess(holdRes);
    const hold = unwrap(holdRes.body);

    const holdData = await getHold(workspace.id, matter.id, hold.id);
    const holdEtag = holdData.etag!;

    const custodianData = await getCustodian(workspace.id, matter.id, custodian.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/custodians/${custodian.id}/state`,
      { to_status: 'DEPARTED' },
      custodianData.etag!,
      idempotencyKey('c9-dep')
    );

    const issueRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'ISSUED' },
      holdEtag,
      idempotencyKey('c9-iss')
    );
    expectSuccess(issueRes);

    const holdAfter = await getHold(workspace.id, matter.id, hold.id);
    expect(holdAfter.status).toBe('ISSUED');
  });

  test('CUSTODIAN_010: Starting collection for departed custodian (non-court-ordered hold) fails', async () => {

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
        data_source: 'EMAIL',
        estimated_bytes: 100
      },
      idempotencyKey('c10-c')
    );
    expectSuccess(collRes);
    const collection = unwrap(collRes.body);

    let collData = await getCollection(workspace.id, matter.id, collection.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'SUBMITTED' },
      collData.etag!,
      idempotencyKey('c10-sub')
    );

    collData = await getCollection(workspace.id, matter.id, collection.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'APPROVED' },
      collData.etag!,
      idempotencyKey('c10-app')
    );

    const custodianData = await getCustodian(workspace.id, matter.id, custodian.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/custodians/${custodian.id}/state`,
      { to_status: 'DEPARTED' },
      custodianData.etag!,
      idempotencyKey('c10-dep')
    );

    collData = await getCollection(workspace.id, matter.id, collection.id);

    const startRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'IN_PROGRESS' },
      collData.etag!,
      idempotencyKey('c10-start')
    );

    await expectErrorCode(startRes, 'ERR_CUSTODIAN_DEPARTED');

    const collAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collAfter.status).toBe('APPROVED');
  });

  test('CUSTODIAN_011: Starting collection for departed custodian fails', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const holdRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'NonCourtHold',
        legal_basis: 'LITIGATION',
        scope: 'ALL_DATA',
        is_court_ordered: false,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('c11-h')
    );
    expectSuccess(holdRes);
    const hold = unwrap(holdRes.body);

    let holdData = await getHold(workspace.id, matter.id, hold.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'ISSUED' },
      holdData.etag!,
      idempotencyKey('c11-iss')
    );

    holdData = await getHold(workspace.id, matter.id, hold.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'ACTIVE' },
      holdData.etag!,
      idempotencyKey('c11-act')
    );

    const collRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections`,
      {
        hold_id: hold.id,
        custodian_id: custodian.id,
        data_source: 'EMAIL',
        estimated_bytes: 100
      },
      idempotencyKey('c11-c')
    );
    expectSuccess(collRes);
    const collection = unwrap(collRes.body);

    let collData = await getCollection(workspace.id, matter.id, collection.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'SUBMITTED' },
      collData.etag!,
      idempotencyKey('c11-sub')
    );

    collData = await getCollection(workspace.id, matter.id, collection.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'APPROVED' },
      collData.etag!,
      idempotencyKey('c11-app')
    );

    collData = await getCollection(workspace.id, matter.id, collection.id);
    expect(collData.status).toBe('APPROVED');

    const custodianData = await getCustodian(workspace.id, matter.id, custodian.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/custodians/${custodian.id}/state`,
      { to_status: 'DEPARTED' },
      custodianData.etag!,
      idempotencyKey('c11-dep')
    );

    collData = await getCollection(workspace.id, matter.id, collection.id);

    const startRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/collections/${collection.id}/state`,
      { to_status: 'IN_PROGRESS' },
      collData.etag!,
      idempotencyKey('c11-start')
    );

    await expectErrorCode(startRes, 'ERR_CUSTODIAN_DEPARTED');

    const collAfter = await getCollection(workspace.id, matter.id, collection.id);
    expect(collAfter.status).toBe('APPROVED');
  });

  test('CUSTODIAN_012: Purging custodian releases DRAFT non-court-ordered hold', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const holdRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'Hold3',
        legal_basis: 'LITIGATION',
        scope: 'ALL_DATA',
        is_court_ordered: false,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('c12-h')
    );
    expectSuccess(holdRes);
    const hold = unwrap(holdRes.body);

    let holdData = await getHold(workspace.id, matter.id, hold.id);
    expect(holdData.status).toBe('DRAFT');

    const custodianData = await getCustodian(workspace.id, matter.id, custodian.id);
    const purgeRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/custodians/${custodian.id}/state`,
      { to_status: 'PURGED' },
      custodianData.etag!,
      idempotencyKey('c12-p')
    );
    expectSuccess(purgeRes);

    holdData = await getHold(workspace.id, matter.id, hold.id);
    expect(holdData.status).toBe('RELEASED');
  });

  test('CUSTODIAN_013: Purging custodian withdraws DRAFT collection', async () => {

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
    expect(collData.status).toBe('DRAFT');

    const custodianData = await getCustodian(workspace.id, matter.id, custodian.id);
    const purgeRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/custodians/${custodian.id}/state`,
      { to_status: 'PURGED' },
      custodianData.etag!,
      idempotencyKey('c13-p')
    );
    expectSuccess(purgeRes);

    collData = await getCollection(workspace.id, matter.id, collection.id);
    expect(collData.status).toBe('WITHDRAWN');

    const wsData = await getWorkspace(workspace.id);
    expect(wsData.bytes_reserved).toBe(0);
  });

  test('CUSTODIAN_014: Departing custodian does not change matter posture', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    let matterData = await getMatter(workspace.id, matter.id);
    expect(matterData.posture).toBe('OPEN');

    const custodianData = await getCustodian(workspace.id, matter.id, custodian.id);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/custodians/${custodian.id}/state`,
      { to_status: 'DEPARTED' },
      custodianData.etag!,
      idempotencyKey('c14')
    );
    expectSuccess(res);

    matterData = await getMatter(workspace.id, matter.id);
    expect(matterData.posture).toBe('OPEN');
  });

  test('CUSTODIAN_015: Purging a DEPARTED custodian succeeds', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian1 = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const custRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/custodians`,
      { full_name: 'Temp', email: 't@example.com' },
      idempotencyKey('c15-new')
    );
    expectSuccess(custRes);
    const custodian2 = unwrap(custRes.body);

    let custData = await getCustodian(workspace.id, matter.id, custodian2.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/custodians/${custodian2.id}/state`,
      { to_status: 'DEPARTED' },
      custData.etag!,
      idempotencyKey('c15-dep')
    );

    custData = await getCustodian(workspace.id, matter.id, custodian2.id);
    expect(custData.status).toBe('DEPARTED');

    const purgeRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/custodians/${custodian2.id}/state`,
      { to_status: 'PURGED' },
      custData.etag!,
      idempotencyKey('c15-p')
    );
    expectSuccess(purgeRes);

    const custAfter = await getCustodian(workspace.id, matter.id, custodian2.id);
    expect(custAfter.status).toBe('PURGED');
  });

  test('CUSTODIAN_016: Invalid custodian status value fails with ERR_BAD_REQUEST', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian1 = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const custRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/custodians`,
      { full_name: 'WrongPath', email: 'wp@example.com' },
      idempotencyKey('c16')
    );
    expectSuccess(custRes);
    const custodian2 = unwrap(custRes.body);

    const custData = await getCustodian(workspace.id, matter.id, custodian2.id);

    const res = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/custodians/${custodian2.id}/state`,
      { to_status: 'UNKNOWN' },
      custData.etag!,
      idempotencyKey('c16-bad')
    );

    await expectErrorCode(res, 'ERR_BAD_REQUEST');

    const custAfter = await getCustodian(workspace.id, matter.id, custodian2.id);
    expect(custAfter.status).toBe('ACTIVE');
  });

  test('CUSTODIAN_017: Creating hold with PURGED custodian fails', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const custData = await getCustodian(workspace.id, matter.id, custodian.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/custodians/${custodian.id}/state`,
      { to_status: 'PURGED' },
      custData.etag!,
      idempotencyKey('c17-p')
    );

    const custAfter = await getCustodian(workspace.id, matter.id, custodian.id);
    expect(custAfter.status).toBe('PURGED');

    const holdRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'NewHold',
        legal_basis: 'LITIGATION',
        scope: 'ALL_DATA',
        is_court_ordered: false,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('c17-h')
    );

    await expectErrorCode(holdRes, 'ERR_CUSTODIAN_PURGED');
  });

  test('CUSTODIAN_018: Idempotency-Key replay returns same result for custodian transition', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const custData = await getCustodian(workspace.id, matter.id, custodian.id);
    const idempKey = idempotencyKey('c18-dep');

    const res1 = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/custodians/${custodian.id}/state`,
      { to_status: 'DEPARTED' },
      custData.etag!,
      idempKey
    );
    expectSuccess(res1);

    const res2 = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/custodians/${custodian.id}/state`,
      { to_status: 'DEPARTED' },
      custData.etag!,
      idempKey
    );

    expectSuccess(res2);
    expect(res2.status).toBe(res1.status);

    expect(res2.body).toEqual(res1.body);

    const custAfterReplay = await getCustodian(workspace.id, matter.id, custodian.id);
    expect(custAfterReplay.status).toBe('DEPARTED');
  });

  test('CUSTODIAN_019: Purging custodian releases hold and leaves matter posture OPEN', async () => {

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

    let holdData = await getHold(workspace.id, matter.id, hold.id);
    expect(holdData.status).toBe('ACTIVE');

    const custData = await getCustodian(workspace.id, matter.id, custodian.id);

    const purgeRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/custodians/${custodian.id}/state`,
      { to_status: 'PURGED' },
      custData.etag!,
      idempotencyKey('c19')
    );
    expectSuccess(purgeRes);

    holdData = await getHold(workspace.id, matter.id, hold.id);
    expect(holdData.status).toBe('RELEASED');

    const matterData = await getMatter(workspace.id, matter.id);
    expect(matterData.posture).toBe('OPEN');
  });

  test('CUSTODIAN_020: Purging custodian releases ISSUED non-court-ordered hold', async () => {

    const workspace = await createWorkspace({ quota_bytes: 1000 });
    const matter = await createMatter(workspace.id, { matter_type: 'LITIGATION' });
    const custodian = await createCustodian(workspace.id, matter.id);
    await activateMatter(workspace.id, matter.id);

    const holdRes = await post(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds`,
      {
        title: 'HoldX',
        legal_basis: 'LITIGATION',
        scope: 'ALL_DATA',
        is_court_ordered: false,
        custodian_ids: [custodian.id]
      },
      idempotencyKey('c20-h')
    );
    expectSuccess(holdRes);
    const hold = unwrap(holdRes.body);

    let holdData = await getHold(workspace.id, matter.id, hold.id);
    await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/holds/${hold.id}/state`,
      { to_status: 'ISSUED' },
      holdData.etag!,
      idempotencyKey('c20-iss')
    );

    holdData = await getHold(workspace.id, matter.id, hold.id);
    expect(holdData.status).toBe('ISSUED');

    const custData = await getCustodian(workspace.id, matter.id, custodian.id);

    const purgeRes = await postState(
      `/workspaces/${workspace.id}/matters/${matter.id}/custodians/${custodian.id}/state`,
      { to_status: 'PURGED' },
      custData.etag!,
      idempotencyKey('c20-p')
    );
    expectSuccess(purgeRes);

    const holdAfter = await getHold(workspace.id, matter.id, hold.id);
    expect(holdAfter.status).toBe('RELEASED');
  });

});
