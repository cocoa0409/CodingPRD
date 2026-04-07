import {
  getAs,
  postAs,
  putWithVersion,
  postAction,
  postWithVersion,
} from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
  expectPostureNormal,
  expectPostureRestricted,
  expectOpenClaimCount,
  expectEpisodeRetracted,
  expectEpisodeClear,
  expectEpisodeUnderReview,
  expectReservationCredited,
  expectReservationCanceled,
  expectDealBudget,
  expectPodcastInventory,
} from '../../../test-helpers/assertions';
import {
  createFixtureStackGeneralStd,
  createFixtureHoldPre30,
  createFixtureAcceptedClaimAuditPending,
  createFixtureRestrictedTwoOpenClaims,
  createPodcast,
  createEpisode,
  createDeal,
  createReservation,
  createClaim,
  closeClaim,
  getPodcast,
  getEpisode,
  getDeal,
  activateDeal,
  approveReservation,
  runOps,
  findReservation,
  submitEpisode,
} from '../../../test-helpers/resources';
import {
  PLACEMENT,
  CONTENT_RATING,
  BRAND_TIER,
  RESERVATION_STATUS,
  EPISODE_STATUS,
  CLEARANCE,
  POSTURE,
  ERROR_CODES,
  CLAIM_KIND,
  CLAIM_OUTCOME,
} from '../../../test-helpers/constants';

describe('Feature 6: Claims and Posture', () => {

  test('CLAIM_001: Creating claim sets episode UNDER_REVIEW and increments open_claim_count', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();

    const res = await postAs(`/podcasts/${podcast.id}/claims`, {
      episode_id: episode.id,
      kind: CLAIM_KIND.RIGHTS,
    });

    expectSuccess(res);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.open_claim_count).toBe(1);

    const episodeData = await getEpisode(podcast.id, episode.id);
    expect(episodeData.clearance).toBe(CLEARANCE.UNDER_REVIEW);
  });

  test('CLAIM_002: Creating duplicate claim (same episode + kind) fails with ERR_DUPLICATE_CLAIM', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    await createClaim(podcast.id, {
      episode_id: episode.id,
      kind: CLAIM_KIND.RIGHTS,
    });

    const res = await postAs(`/podcasts/${podcast.id}/claims`, {
      episode_id: episode.id,
      kind: CLAIM_KIND.RIGHTS,
    });

    expectErrorCode(res, ERROR_CODES.ERR_DUPLICATE_CLAIM);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.open_claim_count).toBe(1);
  });

  test('CLAIM_003: Creating second claim of different kind triggers RESTRICTED posture', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    await createClaim(podcast.id, {
      episode_id: episode.id,
      kind: CLAIM_KIND.RIGHTS,
    });

    const res = await postAs(`/podcasts/${podcast.id}/claims`, {
      episode_id: episode.id,
      kind: CLAIM_KIND.BRAND_SAFETY,
    });

    expectSuccess(res);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.open_claim_count).toBe(2);
    expect(podcastData.posture).toBe(POSTURE.RESTRICTED);
  });

  test('CLAIM_004: Closing claim with REJECTED resolves dispute and clears episode', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const claim = await createClaim(podcast.id, {
      episode_id: episode.id,
      kind: CLAIM_KIND.RIGHTS,
    });

    const res = await postWithVersion(
      `/podcasts/${podcast.id}/claims/${claim.id}/close`,
      { outcome: CLAIM_OUTCOME.REJECTED },
      claim.version
    );

    expectSuccess(res);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.open_claim_count).toBe(0);

    const episodeData = await getEpisode(podcast.id, episode.id);
    expect(episodeData.clearance).toBe(CLEARANCE.CLEAR);
  });

  test('CLAIM_005: Closing claim with WITHDRAWN resolves dispute and clears episode', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const claim = await createClaim(podcast.id, {
      episode_id: episode.id,
      kind: CLAIM_KIND.RIGHTS,
    });

    const res = await postWithVersion(
      `/podcasts/${podcast.id}/claims/${claim.id}/close`,
      { outcome: CLAIM_OUTCOME.WITHDRAWN },
      claim.version
    );

    expectSuccess(res);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.open_claim_count).toBe(0);

    const episodeData = await getEpisode(podcast.id, episode.id);
    expect(episodeData.clearance).toBe(CLEARANCE.CLEAR);
  });

  test('CLAIM_006: Accepted claim retracts episode and credits settled reservation', async () => {

    const { podcast, episode, deal, reservation, claim } = await createFixtureAcceptedClaimAuditPending();

    const res = await getAs(`/podcasts/${podcast.id}/episodes/${episode.id}`);

    expectSuccess(res);
    const episodeData = res.body.data ?? res.body;
    expect(episodeData.status).toBe(EPISODE_STATUS.RETRACTED);
    expect(episodeData.clearance).toBe(CLEARANCE.CLEAR);

    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.CREDITED);
  });

  test('CLAIM_007: Accepted claim puts podcast in RESTRICTED posture with open_claim_count=0', async () => {

    const { podcast, episode, deal, reservation, claim } = await createFixtureAcceptedClaimAuditPending();

    const res = await getAs(`/podcasts/${podcast.id}`);

    expectSuccess(res);
    const podcastData = res.body.data ?? res.body;
    expect(podcastData.open_claim_count).toBe(0);
    expect(podcastData.posture).toBe(POSTURE.RESTRICTED);
  });

  test('CLAIM_008: Ops run clears RESTRICTED posture after accepted claim with no open claims', async () => {

    const { podcast, episode, deal, reservation, claim } = await createFixtureAcceptedClaimAuditPending();

    const podcastBefore = await getPodcast(podcast.id);
    expect(podcastBefore.posture).toBe(POSTURE.RESTRICTED);

    const res = await postWithVersion(
      `/podcasts/${podcast.id}/run_ops`,
      {},
      podcastBefore.version!
    );

    expectSuccess(res);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.posture).toBe(POSTURE.NORMAL);
  });

  test('CLAIM_009: Closing claim with ACCEPTED retracts episode and sets posture to RESTRICTED', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const claim = await createClaim(podcast.id, {
      episode_id: episode.id,
      kind: CLAIM_KIND.RIGHTS,
    });

    const res = await postWithVersion(
      `/podcasts/${podcast.id}/claims/${claim.id}/close`,
      { outcome: CLAIM_OUTCOME.ACCEPTED },
      claim.version
    );

    expectSuccess(res);

    const episodeData = await getEpisode(podcast.id, episode.id);
    expect(episodeData.status).toBe(EPISODE_STATUS.RETRACTED);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.posture).toBe(POSTURE.RESTRICTED);
    expect(podcastData.open_claim_count).toBe(0);
  });

  test('CLAIM_010: Accepted claim cleans up HOLD reservations and releases held inventory', async () => {

    const { podcast, episode, deal, reservation } = await createFixtureHoldPre30();
    const claim = await createClaim(podcast.id, {
      episode_id: episode.id,
      kind: CLAIM_KIND.RIGHTS,
    });

    const podcastBefore = await getPodcast(podcast.id);
    expect(podcastBefore.ad_held_seconds).toBe(30);

    const dealBefore = await getDeal(podcast.id, deal.id);
    expect(dealBefore.budget_held_cents).toBe(1000);

    const res = await postWithVersion(
      `/podcasts/${podcast.id}/claims/${claim.id}/close`,
      { outcome: CLAIM_OUTCOME.ACCEPTED },
      claim.version
    );

    expectSuccess(res);

    const episodeData = await getEpisode(podcast.id, episode.id);
    expect(episodeData.status).toBe(EPISODE_STATUS.RETRACTED);

    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.CANCELED);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_held_seconds).toBe(0);

    const dealData = await getDeal(podcast.id, deal.id);
    expect(dealData.budget_held_cents).toBe(0);
  });

  test('CLAIM_011: Creating reservation with non-existent deal fails with ERR_NOT_FOUND', async () => {

    const { podcast, episode1, episode2, claim1, claim2 } = await createFixtureRestrictedTwoOpenClaims();

    const fakeDealId = 'non-existent-deal-id';
    const res = await postAs(`/podcasts/${podcast.id}/reservations`, {
      episode_id: episode1.id,
      deal_id: fakeDealId,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });

    expectErrorCode(res, ERROR_CODES.ERR_NOT_FOUND);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.posture).toBe(POSTURE.RESTRICTED);
    expect(podcastData.open_claim_count).toBe(2);
  });

  test('CLAIM_012: Activating deal while podcast is RESTRICTED fails with ERR_PODCAST_RESTRICTED', async () => {

    const { podcast, episode1, episode2, claim1, claim2 } = await createFixtureRestrictedTwoOpenClaims();
    const deal = await createDeal(podcast.id, {
      advertiser_name: 'Acme',
      brand_tier: BRAND_TIER.STANDARD,
      budget_total_cents: 5000,
      slot_price_cents: 1000,
      script_text: 'v1',
    });

    const res = await putWithVersion(
      `/podcasts/${podcast.id}/deals/${deal.id}`,
      { status: 'ACTIVE' },
      deal.version
    );

    expectErrorCode(res, ERROR_CODES.ERR_PODCAST_RESTRICTED);

    const dealData = await getDeal(podcast.id, deal.id);
    expect(dealData.status).toBe('DRAFT');
  });

  test('CLAIM_013: Publishing episode while podcast is RESTRICTED fails with ERR_PODCAST_RESTRICTED', async () => {

    const { podcast, episode1, episode2, claim1, claim2 } = await createFixtureRestrictedTwoOpenClaims();
    const submitted = await submitEpisode(podcast.id, episode1.id, episode1.version);

    const res = await postAction(
      `/podcasts/${podcast.id}/episodes/${episode1.id}/publish`,
      submitted.version
    );

    expectErrorCode(res, ERROR_CODES.ERR_PODCAST_RESTRICTED);

    const episodeData = await getEpisode(podcast.id, episode1.id);
    expect(episodeData.status).toBe(EPISODE_STATUS.SUBMITTED);
  });

  test('CLAIM_014: Closing one of two claims drops open_claim_count and restores NORMAL posture', async () => {

    const { podcast, episode1, episode2, claim1, claim2 } = await createFixtureRestrictedTwoOpenClaims();
    await closeClaim(podcast.id, claim1.id, claim1.version, 'REJECTED');

    const res = await getAs(`/podcasts/${podcast.id}`);

    expectSuccess(res);
    const podcastData = res.body.data ?? res.body;
    expect(podcastData.open_claim_count).toBe(1);
    expect(podcastData.posture).toBe(POSTURE.NORMAL);
  });

  test('CLAIM_015: Creating new claim while RESTRICTED (due to accepted claim) keeps posture RESTRICTED', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const claim = await createClaim(podcast.id, {
      episode_id: episode.id,
      kind: CLAIM_KIND.RIGHTS,
    });
    await closeClaim(podcast.id, claim.id, claim.version, 'ACCEPTED');

    const podcastBefore = await getPodcast(podcast.id);
    expect(podcastBefore.posture).toBe(POSTURE.RESTRICTED);

    const episode2 = await createEpisode(podcast.id, {
      title: 'Ep2',
      content_rating: CONTENT_RATING.GENERAL,
      ad_slots_total_seconds: 60,
    });

    const res = await postAs(`/podcasts/${podcast.id}/claims`, {
      episode_id: episode2.id,
      kind: CLAIM_KIND.BRAND_SAFETY,
    });

    expectSuccess(res);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.open_claim_count).toBe(1);
    expect(podcastData.posture).toBe(POSTURE.RESTRICTED);
  });

  test('CLAIM_016: Creating new RIGHTS claim after closing previous RIGHTS claim succeeds', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const claim = await createClaim(podcast.id, {
      episode_id: episode.id,
      kind: CLAIM_KIND.RIGHTS,
    });
    await closeClaim(podcast.id, claim.id, claim.version, 'REJECTED');

    const podcastBefore = await getPodcast(podcast.id);
    expect(podcastBefore.open_claim_count).toBe(0);

    const res = await postAs(`/podcasts/${podcast.id}/claims`, {
      episode_id: episode.id,
      kind: CLAIM_KIND.RIGHTS,
    });

    expectSuccess(res);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.open_claim_count).toBe(1);
  });

  test('CLAIM_017: Closing claim with wrong If-Match version fails with ERR_VERSION_CONFLICT', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const claim = await createClaim(podcast.id, {
      episode_id: episode.id,
      kind: CLAIM_KIND.RIGHTS,
    });

    const wrongVersion = claim.version + 100;
    const res = await postWithVersion(
      `/podcasts/${podcast.id}/claims/${claim.id}/close`,
      { outcome: CLAIM_OUTCOME.REJECTED },
      wrongVersion
    );

    expectErrorCode(res, ERROR_CODES.ERR_VERSION_CONFLICT);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.open_claim_count).toBe(1);

    const episodeData = await getEpisode(podcast.id, episode.id);
    expect(episodeData.clearance).toBe(CLEARANCE.UNDER_REVIEW);
  });

  test('CLAIM_018: Closing already closed claim fails with ERR_INVALID_STATE', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const claim = await createClaim(podcast.id, {
      episode_id: episode.id,
      kind: CLAIM_KIND.RIGHTS,
    });
    const closedClaim = await closeClaim(podcast.id, claim.id, claim.version, 'REJECTED');

    const res = await postWithVersion(
      `/podcasts/${podcast.id}/claims/${claim.id}/close`,
      { outcome: CLAIM_OUTCOME.REJECTED },
      closedClaim.version
    );

    expectErrorCode(res, ERROR_CODES.ERR_INVALID_STATE);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.open_claim_count).toBe(0);
  });

  test('CLAIM_020: Closing one of two claims with WITHDRAWN drops open_claim_count and restores NORMAL posture', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const claim1 = await createClaim(podcast.id, {
      episode_id: episode.id,
      kind: CLAIM_KIND.RIGHTS,
    });
    const claim2 = await createClaim(podcast.id, {
      episode_id: episode.id,
      kind: CLAIM_KIND.BRAND_SAFETY,
    });

    const podcastBefore = await getPodcast(podcast.id);
    expect(podcastBefore.open_claim_count).toBe(2);
    expect(podcastBefore.posture).toBe(POSTURE.RESTRICTED);

    const res = await postWithVersion(
      `/podcasts/${podcast.id}/claims/${claim2.id}/close`,
      { outcome: CLAIM_OUTCOME.WITHDRAWN },
      claim2.version
    );

    expectSuccess(res);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.open_claim_count).toBe(1);
    expect(podcastData.posture).toBe(POSTURE.NORMAL);
  });

});
