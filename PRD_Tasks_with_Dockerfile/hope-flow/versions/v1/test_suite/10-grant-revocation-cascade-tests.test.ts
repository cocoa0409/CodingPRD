import { postAs } from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
} from '../../../test-helpers/assertions';
import {
  createCampaign,
  getCampaign,
  createContribution,
  getContribution,
  allocateContribution,
  createCause,
  getCause,
  createGrant,
  getGrant,
  createDisbursement,
} from '../../../test-helpers/resources';
import {
  FX_CAMPAIGN,
  FX_CONTRIBUTION_WITH_MATCH,
} from '../../../test-helpers/fixtures';

describe('Feature 10: Grant Revocation Cascade Tests', () => {

  test('REVOKE_001: revoking grant claws back matches and reduces cause allocations proportionally', async () => {

    const { campaign, grant, contribution } = await FX_CONTRIBUTION_WITH_MATCH();

    const cause = await createCause(campaign.id, {
      name: 'Aid',
      target_amount: 5000,
      priority: 1,
    });

    await allocateContribution(campaign.id, contribution.id, {
      cause_id: cause.id,
      amount: 1970,
    });

    const preRevokeCampaign = await getCampaign(campaign.id);
    expect(preRevokeCampaign.match_total).toBe(1000);
    expect(preRevokeCampaign.allocated_total).toBe(1970);

    const preRevokeContribution = await getContribution(campaign.id, contribution.id);
    expect(preRevokeContribution.matched_amount).toBe(1000);

    const preRevokeCause = await getCause(campaign.id, cause.id);
    expect(preRevokeCause.allocated_amount).toBe(1970);

    const res = await postAs(
      `/campaigns/${campaign.id}/grants/${grant.id}/revoke`,
      {}
    );

    expectSuccess(res);

    const revokedGrant = await getGrant(campaign.id, grant.id);
    expect(revokedGrant.status).toBe('REVOKED');

    const updatedContribution = await getContribution(campaign.id, contribution.id);
    expect(updatedContribution.matched_amount).toBe(0);

    const updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.match_total).toBe(0);

    const updatedCause = await getCause(campaign.id, cause.id);
    expect(updatedCause.allocated_amount).toBe(970);
  });

  test('REVOKE_002: revoking grant removes matched portion from contribution allocations', async () => {

    const { campaign, grant, contribution } = await FX_CONTRIBUTION_WITH_MATCH();

    const cause = await createCause(campaign.id, {
      name: 'Aid',
      target_amount: 5000,
      priority: 1,
    });

    await allocateContribution(campaign.id, contribution.id, {
      cause_id: cause.id,
      amount: 1970,
    });

    const preRevokeContribution = await getContribution(campaign.id, contribution.id);
    const preAllocationAmount = preRevokeContribution.allocations.find(
      (a: { cause_id: string; amount: number }) => a.cause_id === cause.id
    )?.amount;
    expect(preAllocationAmount).toBe(1970);

    const res = await postAs(
      `/campaigns/${campaign.id}/grants/${grant.id}/revoke`,
      {}
    );

    expectSuccess(res);

    const revokedGrant = await getGrant(campaign.id, grant.id);
    expect(revokedGrant.status).toBe('REVOKED');

    const updatedContribution = await getContribution(campaign.id, contribution.id);
    expect(updatedContribution.matched_amount).toBe(0);

    const postAllocationAmount = updatedContribution.allocations.find(
      (a: { cause_id: string; amount: number }) => a.cause_id === cause.id
    )?.amount;
    expect(postAllocationAmount).toBe(970);

    const updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.match_total).toBe(0);

    const updatedCause = await getCause(campaign.id, cause.id);
    expect(updatedCause.allocated_amount).toBe(970);
  });

  test('REVOKE_003: revoking grant claws back matches from all matched contributions', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const grant = await createGrant(campaign.id, {
      sponsor_name: 'Corp',
      match_ratio: 1.0,
      cap_amount: 5000,
    });

    const c1 = await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 1000,
    });

    const c2 = await createContribution(campaign.id, {
      donor_name: 'B',
      donor_email: 'b@t.com',
      gross_amount: 500,
    });

    const preRevokeC1 = await getContribution(campaign.id, c1.id);
    expect(preRevokeC1.matched_amount).toBe(1000);

    const preRevokeC2 = await getContribution(campaign.id, c2.id);
    expect(preRevokeC2.matched_amount).toBe(500);

    const preRevokeCampaign = await getCampaign(campaign.id);
    expect(preRevokeCampaign.match_total).toBe(1500);

    const res = await postAs(
      `/campaigns/${campaign.id}/grants/${grant.id}/revoke`,
      {}
    );

    expectSuccess(res);

    const updatedC1 = await getContribution(campaign.id, c1.id);
    expect(updatedC1.matched_amount).toBe(0);

    const updatedC2 = await getContribution(campaign.id, c2.id);
    expect(updatedC2.matched_amount).toBe(0);

    const revokedGrant = await getGrant(campaign.id, grant.id);
    expect(revokedGrant.status).toBe('REVOKED');

    const updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.match_total).toBe(0);
  });

  test('REVOKE_004: revoking grant triggers cause status recalculation to OPEN', async () => {

    const { campaign } = await FX_CAMPAIGN();

    const grant = await createGrant(campaign.id, {
      sponsor_name: 'Corp',
      match_ratio: 1.0,
      cap_amount: 5000,
    });

    const cause = await createCause(campaign.id, {
      name: 'Aid',
      target_amount: 1000,
      priority: 1,
      threshold_percent: 80,
    });

    const contribution = await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 500,
    });

    const preAllocContribution = await getContribution(campaign.id, contribution.id);
    expect(preAllocContribution.matched_amount).toBe(500);

    await allocateContribution(campaign.id, contribution.id, {
      cause_id: cause.id,
      amount: 985,
    });

    const preRevokeCause = await getCause(campaign.id, cause.id);
    expect(preRevokeCause.status).toBe('THRESHOLD_MET');
    expect(preRevokeCause.allocated_amount).toBe(985);

    const res = await postAs(
      `/campaigns/${campaign.id}/grants/${grant.id}/revoke`,
      {}
    );

    expectSuccess(res);

    const updatedCause = await getCause(campaign.id, cause.id);

    expect(updatedCause.allocated_amount).toBe(485);

    expect(updatedCause.status).toBe('OPEN');
  });

  test('REVOKE_005: revoking grant fails when pending disbursement would be underfunded', async () => {

    const { campaign, grant, contribution } = await FX_CONTRIBUTION_WITH_MATCH();

    const cause = await createCause(campaign.id, {
      name: 'Aid',
      target_amount: 3000,
      priority: 1,
      threshold_percent: 50,
    });

    await allocateContribution(campaign.id, contribution.id, {
      cause_id: cause.id,
      amount: 1970,
    });

    const preRevokeCause = await getCause(campaign.id, cause.id);
    expect(preRevokeCause.status).toBe('THRESHOLD_MET');
    expect(preRevokeCause.allocated_amount).toBe(1970);

    const disbursement = await createDisbursement(campaign.id, {
      cause_id: cause.id,
      beneficiary_name: 'Ben',
      amount: 1000,
    });

    const preRevokeCampaign = await getCampaign(campaign.id);
    const preRevokeContribution = await getContribution(campaign.id, contribution.id);

    const res = await postAs(
      `/campaigns/${campaign.id}/grants/${grant.id}/revoke`,
      {}
    );

    await expectErrorCode(res, 'ERR_DISBURSEMENT_BLOCKED');

    const errorBody = JSON.stringify(res.body);
    expect(errorBody).toContain(disbursement.id);

    const unchangedGrant = await getGrant(campaign.id, grant.id);
    expect(unchangedGrant.status).toBe('ACTIVE');

    const unchangedContribution = await getContribution(campaign.id, contribution.id);
    expect(unchangedContribution.matched_amount).toBe(preRevokeContribution.matched_amount);

    const unchangedCampaign = await getCampaign(campaign.id);
    expect(unchangedCampaign.match_total).toBe(preRevokeCampaign.match_total);

    const unchangedCause = await getCause(campaign.id, cause.id);
    expect(unchangedCause.allocated_amount).toBe(1970);
  });
});
