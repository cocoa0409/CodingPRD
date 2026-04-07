import {
  postAs,
  getAs,
} from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
} from '../../../test-helpers/assertions';
import {
  getCampaign,
  getContribution,
  getGrant,
  createGrant,
  createContribution,
  createPledge,
  suspendGrant,
  unwrap,
} from '../../../test-helpers/resources';
import {
  FX_CAMPAIGN,
  FX_CAMPAIGN_WITH_GRANT,
  FX_CONTRIBUTION_WITH_MATCH,
  FX_MULTI_GRANT,
} from '../../../test-helpers/fixtures';
import { ERROR_CODES } from '../../../test-helpers/constants';

describe('Grant Tests', () => {

  test('GRANT_001: POST /campaigns/:C/grants creates grant with defaults', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const res = await postAs(`/campaigns/${campaign.id}/grants`, {
      sponsor_name: 'Acme Corp',
      match_ratio: 1.0,
      cap_amount: 5000,
    });

    expectSuccess(res);
    const grant = unwrap(res.body);
    expect(grant.id).toBeDefined();
    expect(grant.sponsor_name).toBe('Acme Corp');
    expect(grant.match_ratio).toBe(1.0);
    expect(grant.cap_amount).toBe(5000);
    expect(grant.status).toBe('ACTIVE');
    expect(grant.matched_so_far).toBe(0);
    expect(grant.min_contribution).toBe(0);
    expect(grant.excludes_pledge_fulfillment).toBe(false);
  });

  test('GRANT_002: Contribution receives 1:1 matching from active grant', async () => {
    const { campaign, grant } = await FX_CAMPAIGN_WITH_GRANT();

    const res = await postAs(`/campaigns/${campaign.id}/contributions`, {
      donor_name: 'Bob',
      donor_email: 'bob@test.com',
      gross_amount: 1000,
      match_eligible: true,
    });

    expectSuccess(res);
    const contribution = unwrap(res.body);
    expect(contribution.matched_amount).toBe(1000);

    const updatedGrant = await getGrant(campaign.id, grant.id);
    expect(updatedGrant.matched_so_far).toBe(1000);

    const updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.match_total).toBe(1000);
  });

  test('GRANT_003: Contribution receives 0.5 ratio matching', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const grant = await createGrant(campaign.id, {
      sponsor_name: 'Half Corp',
      match_ratio: 0.5,
      cap_amount: 5000,
    });

    const res = await postAs(`/campaigns/${campaign.id}/contributions`, {
      donor_name: 'Bob',
      donor_email: 'bob@test.com',
      gross_amount: 1000,
      match_eligible: true,
    });

    expectSuccess(res);
    const contribution = unwrap(res.body);
    expect(contribution.matched_amount).toBe(500);

    const updatedGrant = await getGrant(campaign.id, grant.id);
    expect(updatedGrant.matched_so_far).toBe(500);

    const updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.match_total).toBe(500);
  });

  test('GRANT_004: Grant caps matching at cap_amount and transitions to EXHAUSTED', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const grant = await createGrant(campaign.id, {
      sponsor_name: 'Small Corp',
      match_ratio: 1.0,
      cap_amount: 500,
    });

    const res = await postAs(`/campaigns/${campaign.id}/contributions`, {
      donor_name: 'Bob',
      donor_email: 'bob@test.com',
      gross_amount: 1000,
      match_eligible: true,
    });

    expectSuccess(res);
    const contribution = unwrap(res.body);
    expect(contribution.matched_amount).toBe(500);

    const updatedGrant = await getGrant(campaign.id, grant.id);
    expect(updatedGrant.matched_so_far).toBe(500);
    expect(updatedGrant.status).toBe('EXHAUSTED');

    const updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.match_total).toBe(500);
  });

  test('GRANT_005: EXHAUSTED grant does not match new contributions', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const grant = await createGrant(campaign.id, {
      sponsor_name: 'Small Corp',
      match_ratio: 1.0,
      cap_amount: 500,
    });

    await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 500,
      match_eligible: true,
    });

    const exhaustedGrant = await getGrant(campaign.id, grant.id);
    expect(exhaustedGrant.status).toBe('EXHAUSTED');
    expect(exhaustedGrant.matched_so_far).toBe(500);

    const res = await postAs(`/campaigns/${campaign.id}/contributions`, {
      donor_name: 'B',
      donor_email: 'b@t.com',
      gross_amount: 500,
      match_eligible: true,
    });

    expectSuccess(res);
    const contribution = unwrap(res.body);
    expect(contribution.matched_amount).toBe(0);

    const updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.match_total).toBe(500);
  });

  test('GRANT_006: Non-match-eligible contribution receives no matching', async () => {
    const { campaign, grant } = await FX_CAMPAIGN_WITH_GRANT();

    const res = await postAs(`/campaigns/${campaign.id}/contributions`, {
      donor_name: 'Bob',
      donor_email: 'bob@test.com',
      gross_amount: 1000,
      match_eligible: false,
    });

    expectSuccess(res);
    const contribution = unwrap(res.body);
    expect(contribution.matched_amount).toBe(0);

    const updatedGrant = await getGrant(campaign.id, grant.id);
    expect(updatedGrant.matched_so_far).toBe(0);
  });

  test('GRANT_007: Contribution below min_contribution threshold receives no matching', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const grant = await createGrant(campaign.id, {
      sponsor_name: 'Corp',
      match_ratio: 1.0,
      cap_amount: 5000,
      min_contribution: 500,
    });

    const res = await postAs(`/campaigns/${campaign.id}/contributions`, {
      donor_name: 'Bob',
      donor_email: 'bob@test.com',
      gross_amount: 400,
      match_eligible: true,
    });

    expectSuccess(res);
    const contribution = unwrap(res.body);
    expect(contribution.matched_amount).toBe(0);

    const updatedGrant = await getGrant(campaign.id, grant.id);
    expect(updatedGrant.matched_so_far).toBe(0);
  });

  test('GRANT_008: Contribution exactly at min_contribution threshold receives matching', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const grant = await createGrant(campaign.id, {
      sponsor_name: 'Corp',
      match_ratio: 1.0,
      cap_amount: 5000,
      min_contribution: 500,
    });

    const res = await postAs(`/campaigns/${campaign.id}/contributions`, {
      donor_name: 'Bob',
      donor_email: 'bob@test.com',
      gross_amount: 500,
      match_eligible: true,
    });

    expectSuccess(res);
    const contribution = unwrap(res.body);
    expect(contribution.matched_amount).toBe(500);

    const updatedGrant = await getGrant(campaign.id, grant.id);
    expect(updatedGrant.matched_so_far).toBe(500);
  });

  test('GRANT_009: Grant with excludes_pledge_fulfillment=true does not match pledge fulfillment', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const grant = await createGrant(campaign.id, {
      sponsor_name: 'Corp',
      match_ratio: 1.0,
      cap_amount: 5000,
      excludes_pledge_fulfillment: true,
    });

    const pledge = await createPledge(campaign.id, {
      donor_name: 'Alice',
      donor_email: 'a@t.com',
      amount: 1000,
    });

    const res = await postAs(`/campaigns/${campaign.id}/contributions`, {
      donor_name: 'Alice',
      donor_email: 'a@t.com',
      gross_amount: 1000,
      fulfills_pledge_id: pledge.id,
      match_eligible: true,
    });

    expectSuccess(res);
    const contribution = unwrap(res.body);
    expect(contribution.matched_amount).toBe(0);

    const updatedGrant = await getGrant(campaign.id, grant.id);
    expect(updatedGrant.matched_so_far).toBe(0);
  });

  test('GRANT_010: POST /campaigns/:C/grants/:G/suspend transitions grant to SUSPENDED and preserves existing matches', async () => {
    const { campaign, grant } = await FX_CAMPAIGN_WITH_GRANT();

    const contribution = await createContribution(campaign.id, {
      donor_name: 'Alice',
      donor_email: 'alice@test.com',
      gross_amount: 1000,
      match_eligible: true,
    });

    expect(contribution.matched_amount).toBe(1000);

    const grantBeforeSuspend = await getGrant(campaign.id, grant.id);
    expect(grantBeforeSuspend.matched_so_far).toBe(1000);

    const res = await postAs(`/campaigns/${campaign.id}/grants/${grant.id}/suspend`, {});

    expectSuccess(res);

    const suspendedGrant = await getGrant(campaign.id, grant.id);
    expect(suspendedGrant.status).toBe('SUSPENDED');
    expect(suspendedGrant.matched_so_far).toBe(1000);

    const contributionAfterSuspend = await getContribution(campaign.id, contribution.id);
    expect(contributionAfterSuspend.matched_amount).toBe(1000);
  });

  test('GRANT_011: SUSPENDED grant does not match new contributions', async () => {
    const { campaign, grant } = await FX_CAMPAIGN_WITH_GRANT();

    await suspendGrant(campaign.id, grant.id);

    const suspendedGrant = await getGrant(campaign.id, grant.id);
    expect(suspendedGrant.status).toBe('SUSPENDED');

    const res = await postAs(`/campaigns/${campaign.id}/contributions`, {
      donor_name: 'Bob',
      donor_email: 'bob@test.com',
      gross_amount: 1000,
      match_eligible: true,
    });

    expectSuccess(res);
    const contribution = unwrap(res.body);
    expect(contribution.matched_amount).toBe(0);

    const updatedGrant = await getGrant(campaign.id, grant.id);
    expect(updatedGrant.matched_so_far).toBe(0);
  });

  test('GRANT_012: POST /campaigns/:C/grants/:G/reactivate transitions SUSPENDED grant to ACTIVE', async () => {
    const { campaign, grant } = await FX_CAMPAIGN_WITH_GRANT();

    await suspendGrant(campaign.id, grant.id);

    const suspendedGrant = await getGrant(campaign.id, grant.id);
    expect(suspendedGrant.status).toBe('SUSPENDED');

    const res = await postAs(`/campaigns/${campaign.id}/grants/${grant.id}/reactivate`, {});

    expectSuccess(res);

    const reactivatedGrant = await getGrant(campaign.id, grant.id);
    expect(reactivatedGrant.status).toBe('ACTIVE');
  });

  test('GRANT_013: POST /campaigns/:C/grants/:G/reactivate on EXHAUSTED grant returns ERR_INVALID_STATE', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const grant = await createGrant(campaign.id, {
      sponsor_name: 'Corp',
      match_ratio: 1.0,
      cap_amount: 100,
    });

    await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 100,
      match_eligible: true,
    });

    const exhaustedGrant = await getGrant(campaign.id, grant.id);
    expect(exhaustedGrant.status).toBe('EXHAUSTED');
    expect(exhaustedGrant.matched_so_far).toBe(100);

    const res = await postAs(`/campaigns/${campaign.id}/grants/${grant.id}/reactivate`, {});

    await expectErrorCode(res, ERROR_CODES.INVALID_STATE);

    const unchanged = await getGrant(campaign.id, grant.id);
    expect(unchanged.status).toBe('EXHAUSTED');
  });

  test('GRANT_014: POST /campaigns/:C/grants/:G/revoke claws back all matches', async () => {
    const { campaign, grant, contribution } = await FX_CONTRIBUTION_WITH_MATCH();

    expect(contribution.matched_amount).toBe(1000);
    expect(campaign.match_total).toBe(1000);

    const res = await postAs(`/campaigns/${campaign.id}/grants/${grant.id}/revoke`, {});

    expectSuccess(res);

    const revokedGrant = await getGrant(campaign.id, grant.id);
    expect(revokedGrant.status).toBe('REVOKED');

    const updatedContribution = await getContribution(campaign.id, contribution.id);
    expect(updatedContribution.matched_amount).toBe(0);

    const updatedCampaign = await getCampaign(campaign.id);
    expect(updatedCampaign.match_total).toBe(0);
  });

  test('GRANT_015: POST /campaigns/:C/grants/:G/reactivate on REVOKED grant returns ERR_INVALID_STATE', async () => {
    const { campaign, grant } = await FX_CAMPAIGN_WITH_GRANT();

    const revokeRes = await postAs(`/campaigns/${campaign.id}/grants/${grant.id}/revoke`, {});
    expectSuccess(revokeRes);

    const revokedGrant = await getGrant(campaign.id, grant.id);
    expect(revokedGrant.status).toBe('REVOKED');

    const res = await postAs(`/campaigns/${campaign.id}/grants/${grant.id}/reactivate`, {});

    await expectErrorCode(res, ERROR_CODES.INVALID_STATE);

    const unchanged = await getGrant(campaign.id, grant.id);
    expect(unchanged.status).toBe('REVOKED');
  });

  test('GRANT_016: POST /campaigns/:C/grants/:G/suspend on REVOKED grant returns ERR_INVALID_STATE', async () => {
    const { campaign, grant } = await FX_CAMPAIGN_WITH_GRANT();

    const revokeRes = await postAs(`/campaigns/${campaign.id}/grants/${grant.id}/revoke`, {});
    expectSuccess(revokeRes);

    const revokedGrant = await getGrant(campaign.id, grant.id);
    expect(revokedGrant.status).toBe('REVOKED');

    const res = await postAs(`/campaigns/${campaign.id}/grants/${grant.id}/suspend`, {});

    await expectErrorCode(res, ERROR_CODES.INVALID_STATE);

    const unchanged = await getGrant(campaign.id, grant.id);
    expect(unchanged.status).toBe('REVOKED');
  });

  test('GRANT_017: POST /campaigns/:C/grants/:G/revoke on EXHAUSTED grant succeeds', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const grant = await createGrant(campaign.id, {
      sponsor_name: 'Corp',
      match_ratio: 1.0,
      cap_amount: 100,
    });

    await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 100,
      match_eligible: true,
    });

    const exhaustedGrant = await getGrant(campaign.id, grant.id);
    expect(exhaustedGrant.status).toBe('EXHAUSTED');

    const res = await postAs(`/campaigns/${campaign.id}/grants/${grant.id}/revoke`, {});

    expectSuccess(res);

    const revokedGrant = await getGrant(campaign.id, grant.id);
    expect(revokedGrant.status).toBe('REVOKED');
  });

  test('GRANT_018: POST /campaigns/:C/grants/:G/suspend on EXHAUSTED grant returns ERR_INVALID_STATE', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const grant = await createGrant(campaign.id, {
      sponsor_name: 'Corp',
      match_ratio: 1.0,
      cap_amount: 100,
    });

    await createContribution(campaign.id, {
      donor_name: 'A',
      donor_email: 'a@t.com',
      gross_amount: 100,
      match_eligible: true,
    });

    const exhaustedGrant = await getGrant(campaign.id, grant.id);
    expect(exhaustedGrant.status).toBe('EXHAUSTED');

    const res = await postAs(`/campaigns/${campaign.id}/grants/${grant.id}/suspend`, {});

    await expectErrorCode(res, ERROR_CODES.INVALID_STATE);

    const unchanged = await getGrant(campaign.id, grant.id);
    expect(unchanged.status).toBe('EXHAUSTED');
  });

  test('GRANT_019: Multiple grants match in creation order', async () => {
    const { campaign, grant1, grant2 } = await FX_MULTI_GRANT();

    const res = await postAs(`/campaigns/${campaign.id}/contributions`, {
      donor_name: 'Bob',
      donor_email: 'bob@test.com',
      gross_amount: 1000,
      match_eligible: true,
    });

    expectSuccess(res);
    const contribution = unwrap(res.body);

    expect(contribution.matched_amount).toBe(1500);

    const updatedGrant1 = await getGrant(campaign.id, grant1.id);
    expect(updatedGrant1.matched_so_far).toBe(500);

    const updatedGrant2 = await getGrant(campaign.id, grant2.id);
    expect(updatedGrant2.matched_so_far).toBe(1000);
  });

  test('GRANT_020: First grant exhausts at cap, second grant continues matching', async () => {
    const { campaign } = await FX_CAMPAIGN();

    const grant1 = await createGrant(campaign.id, {
      sponsor_name: 'First',
      match_ratio: 1.0,
      cap_amount: 300,
    });

    const grant2 = await createGrant(campaign.id, {
      sponsor_name: 'Second',
      match_ratio: 0.5,
      cap_amount: 1000,
    });

    const res = await postAs(`/campaigns/${campaign.id}/contributions`, {
      donor_name: 'Bob',
      donor_email: 'bob@test.com',
      gross_amount: 1000,
      match_eligible: true,
    });

    expectSuccess(res);
    const contribution = unwrap(res.body);

    expect(contribution.matched_amount).toBe(800);

    const updatedGrant1 = await getGrant(campaign.id, grant1.id);
    expect(updatedGrant1.status).toBe('EXHAUSTED');
    expect(updatedGrant1.matched_so_far).toBe(300);

    const updatedGrant2 = await getGrant(campaign.id, grant2.id);
    expect(updatedGrant2.matched_so_far).toBe(500);
  });
});
