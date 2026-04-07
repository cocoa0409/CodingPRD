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
  expectEpisodeLive,
  expectReservationCanceled,
  expectReservationApproved,
  expectReservationNeedsReview,
  expectReservationOverbooked,
  expectDealBudget,
  expectPodcastInventory,
  expectDealStatus,
} from '../../../test-helpers/assertions';
import {
  createFixtureStackGeneralStd,
  createFixtureApprovedPre30,
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
  cancelReservation,
  submitEpisode,
  updateEpisode,
  updateDeal,
  findReservation,
  runOps,
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
  DEAL_STATUS,
} from '../../../test-helpers/constants';

describe('Feature 7: Cross-Feature Interaction Tests', () => {

  test('CROSS_001: Script update causes NEEDS_REVIEW which blocks publish', async () => {

    const { podcast, episode, deal, reservation } = await createFixtureApprovedPre30();

    const dealData = await getDeal(podcast.id, deal.id);

    const updatedDeal = await updateDeal(podcast.id, deal.id, dealData.version, {
      script_text: 'Read v2',
    });

    const episodeAfterScriptChange = await getEpisode(podcast.id, episode.id);
    const resvAfterScriptChange = findReservation(episodeAfterScriptChange, reservation.id);
    expect(resvAfterScriptChange?.status).toBe(RESERVATION_STATUS.NEEDS_REVIEW);

    const submitted = await submitEpisode(podcast.id, episode.id, episodeAfterScriptChange.version);

    const res = await postAction(
      `/podcasts/${podcast.id}/episodes/${episode.id}/publish`,
      submitted.version
    );

    expectErrorCode(res, ERROR_CODES.ERR_EPISODE_HAS_UNREVIEWED_RESERVATIONS);

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.NEEDS_REVIEW);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_committed_seconds).toBe(30);
  });

  test('CROSS_002: Re-approval after script change clears NEEDS_REVIEW and allows publish', async () => {

    const { podcast, episode, deal, reservation } = await createFixtureApprovedPre30();

    const dealData = await getDeal(podcast.id, deal.id);

    await updateDeal(podcast.id, deal.id, dealData.version, {
      script_text: 'Read v2',
    });

    const episodeAfterScriptChange = await getEpisode(podcast.id, episode.id);
    const resvNeedsReview = findReservation(episodeAfterScriptChange, reservation.id);
    expect(resvNeedsReview?.status).toBe(RESERVATION_STATUS.NEEDS_REVIEW);

    const approvedResv = await approveReservation(podcast.id, reservation.id, resvNeedsReview!.version);

    expect(approvedResv.status).toBe(RESERVATION_STATUS.APPROVED);
    expect(approvedResv.script_version_pinned).toBe(2);

    const episodeAfterApproval = await getEpisode(podcast.id, episode.id);

    const submitted = await submitEpisode(podcast.id, episode.id, episodeAfterApproval.version);

    const res = await postAction(
      `/podcasts/${podcast.id}/episodes/${episode.id}/publish`,
      submitted.version
    );

    expectSuccess(res);

    const episodeData = await getEpisode(podcast.id, episode.id);
    expect(episodeData.status).toBe(EPISODE_STATUS.LIVE);

    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.APPROVED);
    expect(resv?.script_version_pinned).toBe(2);
  });

  test('CROSS_003: OVERBOOKED stops consuming deal budget when capacity tightened', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();

    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });

    const approvedResv = await approveReservation(podcast.id, reservation.id, reservation.version);

    const dealBeforeTighten = await getDeal(podcast.id, deal.id);
    expect(dealBeforeTighten.budget_committed_cents).toBe(1000);
    expect(dealBeforeTighten.budget_available_cents).toBe(4000);

    const podcastBeforeTighten = await getPodcast(podcast.id);
    expect(podcastBeforeTighten.ad_committed_seconds).toBe(30);

    const episodeData = await getEpisode(podcast.id, episode.id);
    expect(episodeData.ad_slots_committed_seconds).toBe(30);

    await updateEpisode(podcast.id, episode.id, episodeData.version, {
      ad_slots_total_seconds: 20,
    });

    const res = await getAs(`/podcasts/${podcast.id}/deals/${deal.id}`);

    expectSuccess(res);
    const dealDataAfter = res.body.data ?? res.body;
    expect(dealDataAfter.budget_committed_cents).toBe(0);
    expect(dealDataAfter.budget_available_cents).toBe(5000);

    const episodeAfter = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(episodeAfter, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.OVERBOOKED);

    expect(episodeAfter.ad_slots_committed_seconds).toBe(0);

    const podcastAfter = await getPodcast(podcast.id);
    expect(podcastAfter.ad_committed_seconds).toBe(0);
  });

  test('CROSS_004: Canceling reservation is allowed while episode is UNDER_REVIEW', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();

    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });

    const approvedResv = await approveReservation(podcast.id, reservation.id, reservation.version);

    const dealBefore = await getDeal(podcast.id, deal.id);
    expect(dealBefore.budget_committed_cents).toBe(1000);
    expect(dealBefore.budget_available_cents).toBe(4000);

    const claim = await createClaim(podcast.id, {
      episode_id: episode.id,
      kind: CLAIM_KIND.RIGHTS,
    });

    const podcastBefore = await getPodcast(podcast.id);
    const episodeBefore = await getEpisode(podcast.id, episode.id);
    expect(episodeBefore.clearance).toBe(CLEARANCE.UNDER_REVIEW);

    const resvOnEpisode = findReservation(episodeBefore, reservation.id);

    const res = await postAction(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/cancel`,
      resvOnEpisode!.version
    );

    expectSuccess(res);

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.CANCELED);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_committed_seconds).toBe(0);
    expect(podcastData.open_claim_count).toBe(1);

    expect(episodeData.clearance).toBe(CLEARANCE.UNDER_REVIEW);

    const dealAfter = await getDeal(podcast.id, deal.id);
    expect(dealAfter.budget_committed_cents).toBe(0);
    expect(dealAfter.budget_available_cents).toBe(5000);
  });

  test('CROSS_005: Approval allowed after claim is closed with REJECTED', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();

    const claim = await createClaim(podcast.id, {
      episode_id: episode.id,
      kind: CLAIM_KIND.RIGHTS,
    });

    const episodeUnderReview = await getEpisode(podcast.id, episode.id);
    expect(episodeUnderReview.clearance).toBe(CLEARANCE.UNDER_REVIEW);

    const podcastWithClaim = await getPodcast(podcast.id);
    expect(podcastWithClaim.open_claim_count).toBe(1);
    expect(podcastWithClaim.posture).toBe(POSTURE.NORMAL);

    await closeClaim(podcast.id, claim.id, claim.version, 'REJECTED');

    const episodeAfterClose = await getEpisode(podcast.id, episode.id);
    expect(episodeAfterClose.clearance).toBe(CLEARANCE.CLEAR);

    const podcastAfterClose = await getPodcast(podcast.id);
    expect(podcastAfterClose.open_claim_count).toBe(0);
    expect(podcastAfterClose.posture).toBe(POSTURE.NORMAL);

    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });

    const res = await postAction(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/approve`,
      reservation.version
    );

    expectSuccess(res);

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.APPROVED);
    expect(episodeData.clearance).toBe(CLEARANCE.CLEAR);
  });

  test('CROSS_006: Activating deal while podcast is RESTRICTED fails with ERR_PODCAST_RESTRICTED', async () => {

    const { podcast, episode1, episode2, claim1, claim2 } = await createFixtureRestrictedTwoOpenClaims();

    const podcastBefore = await getPodcast(podcast.id);
    expect(podcastBefore.posture).toBe(POSTURE.RESTRICTED);

    const newDeal = await createDeal(podcast.id, {
      advertiser_name: 'Acme',
      brand_tier: BRAND_TIER.STANDARD,
      budget_total_cents: 5000,
      slot_price_cents: 1000,
      script_text: 'v1',
    });

    const res = await putWithVersion(
      `/podcasts/${podcast.id}/deals/${newDeal.id}`,
      { status: DEAL_STATUS.ACTIVE },
      newDeal.version
    );

    expectErrorCode(res, ERROR_CODES.ERR_PODCAST_RESTRICTED);

    const dealData = await getDeal(podcast.id, newDeal.id);
    expect(dealData.status).toBe(DEAL_STATUS.DRAFT);
  });

  test('CROSS_007: Closing one claim reduces open_claim_count but episode remains UNDER_REVIEW if another claim is open', async () => {

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

    const episodeData = await getEpisode(podcast.id, episode.id);
    expect(episodeData.clearance).toBe(CLEARANCE.UNDER_REVIEW);
  });

  test('CROSS_008: Closing deal cancels non-terminal reservations and releases commitments', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();

    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });

    await approveReservation(podcast.id, reservation.id, reservation.version);

    const podcastBefore = await getPodcast(podcast.id);
    expect(podcastBefore.ad_committed_seconds).toBe(30);

    const dealData = await getDeal(podcast.id, deal.id);

    await updateDeal(podcast.id, deal.id, dealData.version, {
      status: DEAL_STATUS.CLOSED,
    });

    const res = await getAs(`/podcasts/${podcast.id}/episodes/${episode.id}`);

    expectSuccess(res);
    const episodeData = res.body.data ?? res.body;

    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.CANCELED);
    expect(episodeData.ad_slots_committed_seconds).toBe(0);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_committed_seconds).toBe(0);
  });

  test('CROSS_009: Accepted claim retracts episode which cannot be published', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();

    const submittedEpisode = await submitEpisode(podcast.id, episode.id, episode.version);

    const claim = await createClaim(podcast.id, {
      episode_id: episode.id,
      kind: CLAIM_KIND.RIGHTS,
    });

    await closeClaim(podcast.id, claim.id, claim.version, 'ACCEPTED');

    const episodeData = await getEpisode(podcast.id, episode.id);
    expect(episodeData.status).toBe(EPISODE_STATUS.RETRACTED);

    const podcastAfterClaim = await getPodcast(podcast.id);
    expect(podcastAfterClaim.posture).toBe(POSTURE.RESTRICTED);

    await runOps(podcast.id, podcastAfterClaim.version!);

    const podcastAfterOps = await getPodcast(podcast.id);
    expect(podcastAfterOps.posture).toBe(POSTURE.NORMAL);

    const episodeBeforePublish = await getEpisode(podcast.id, episode.id);

    const res = await postAction(
      `/podcasts/${podcast.id}/episodes/${episode.id}/publish`,
      episodeBeforePublish.version
    );

    expectErrorCode(res, ERROR_CODES.ERR_INVALID_STATE);

    const episodeAfter = await getEpisode(podcast.id, episode.id);
    expect(episodeAfter.status).toBe(EPISODE_STATUS.RETRACTED);
  });

  test('CROSS_010: Accepted claim cleans up approved reservations as part of retraction', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();

    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.MID_ROLL,
      slot_seconds: 30,
    });

    await approveReservation(podcast.id, reservation.id, reservation.version);

    const podcastBefore = await getPodcast(podcast.id);
    expect(podcastBefore.ad_committed_seconds).toBe(30);

    const episodeBeforeSubmit = await getEpisode(podcast.id, episode.id);
    await submitEpisode(podcast.id, episode.id, episodeBeforeSubmit.version);

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

    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.CANCELED);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_committed_seconds).toBe(0);

    expect(podcastData.posture).toBe(POSTURE.RESTRICTED);
  });

});
