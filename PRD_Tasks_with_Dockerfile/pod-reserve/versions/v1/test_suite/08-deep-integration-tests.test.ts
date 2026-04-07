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
  expectEpisodeLive,
  expectEpisodeSubmitted,
  expectEpisodeUnderReview,
  expectEpisodeClear,
  expectReservationCanceled,
  expectReservationApproved,
  expectReservationNeedsReview,
  expectReservationOverbooked,
  expectReservationCredited,
  expectDealBudget,
  expectPodcastInventory,
} from '../../../test-helpers/assertions';
import {
  createFixtureStackGeneralStd,
  createFixtureStackLiveStd,
  createFixtureApprovedPre30,
  createFixtureAcceptedClaimAuditPending,
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
  settleReservation,
  submitEpisode,
  publishEpisode,
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

describe('Feature 8: Deep Integration Tests', () => {

  test('DEEP_001: Filing claim sets episode UNDER_REVIEW but keeps ad_committed_seconds', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();

    const episode2 = await createEpisode(podcast.id, {
      title: 'Ep2',
      content_rating: CONTENT_RATING.GENERAL,
      ad_slots_total_seconds: 60,
    });

    const reservation1 = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 60,
    });

    await approveReservation(podcast.id, reservation1.id, reservation1.version);

    const reservation2 = await createReservation(podcast.id, {
      episode_id: episode2.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 60,
    });

    await approveReservation(podcast.id, reservation2.id, reservation2.version);

    const podcastBefore = await getPodcast(podcast.id);
    expect(podcastBefore.ad_committed_seconds).toBe(120);

    const res = await postAs(`/podcasts/${podcast.id}/claims`, {
      episode_id: episode.id,
      kind: CLAIM_KIND.RIGHTS,
    });

    expectSuccess(res);

    const episodeData = await getEpisode(podcast.id, episode.id);
    expect(episodeData.clearance).toBe(CLEARANCE.UNDER_REVIEW);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.open_claim_count).toBe(1);
    expect(podcastData.posture).toBe(POSTURE.NORMAL);
    expect(podcastData.ad_committed_seconds).toBe(120);
  });

  test('DEEP_002: Accepted claim retracts episode and credits settled reservation', async () => {

    const { podcast, episode, deal } = await createFixtureStackLiveStd();

    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });

    const approvedResv = await approveReservation(podcast.id, reservation.id, reservation.version);

    const settledResv = await settleReservation(podcast.id, reservation.id, approvedResv.version);

    const podcastAfterSettle = await getPodcast(podcast.id);
    expect(podcastAfterSettle.ad_committed_seconds).toBe(30);

    const dealAfterSettle = await getDeal(podcast.id, deal.id);
    expect(dealAfterSettle.budget_spent_cents).toBe(1000);

    const claimRes = await postAs(`/podcasts/${podcast.id}/claims`, {
      episode_id: episode.id,
      kind: CLAIM_KIND.RIGHTS,
    });
    expectSuccess(claimRes);
    const claim = claimRes.body.data ?? claimRes.body;

    const closeRes = await postWithVersion(
      `/podcasts/${podcast.id}/claims/${claim.id}/close`,
      { outcome: CLAIM_OUTCOME.ACCEPTED },
      claim.version
    );

    expectSuccess(closeRes);

    const episodeData = await getEpisode(podcast.id, episode.id);
    expect(episodeData.status).toBe(EPISODE_STATUS.RETRACTED);

    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.CREDITED);

    const dealData = await getDeal(podcast.id, deal.id);
    expect(dealData.budget_spent_cents).toBe(0);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_committed_seconds).toBe(0);
    expect(podcastData.posture).toBe(POSTURE.RESTRICTED);
  });

  test('DEEP_003: Cancel OVERBOOKED reservation after capacity tightening', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();

    const reservation1 = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });

    await approveReservation(podcast.id, reservation1.id, reservation1.version);

    const reservation2 = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.MID_ROLL,
      slot_seconds: 30,
    });

    const approvedResv2 = await approveReservation(podcast.id, reservation2.id, reservation2.version);

    const episodeBeforeEdit = await getEpisode(podcast.id, episode.id);
    expect(episodeBeforeEdit.ad_slots_committed_seconds).toBe(60);

    await updateEpisode(podcast.id, episode.id, episodeBeforeEdit.version, {
      ad_slots_total_seconds: 30,
    });

    const episodeAfterEdit = await getEpisode(podcast.id, episode.id);
    const resv1OnEpisode = findReservation(episodeAfterEdit, reservation1.id);
    const resv2OnEpisode = findReservation(episodeAfterEdit, reservation2.id);
    expect(resv1OnEpisode?.status).toBe(RESERVATION_STATUS.APPROVED);
    expect(resv2OnEpisode?.status).toBe(RESERVATION_STATUS.OVERBOOKED);

    const res = await postAction(
      `/podcasts/${podcast.id}/reservations/${reservation2.id}/cancel`,
      resv2OnEpisode!.version
    );

    expectSuccess(res);

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resv2 = findReservation(episodeData, reservation2.id);
    expect(resv2?.status).toBe(RESERVATION_STATUS.CANCELED);

    const overbookedReservations = episodeData.reservations?.filter(
      (r: any) => r.status === RESERVATION_STATUS.OVERBOOKED
    );
    expect(overbookedReservations?.length ?? 0).toBe(0);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_committed_seconds).toBe(30);
  });

  test('DEEP_004: Closing deal cancels NEEDS_REVIEW reservations', async () => {

    const { podcast, episode, deal, reservation } = await createFixtureApprovedPre30();

    const dealBefore = await getDeal(podcast.id, deal.id);

    const dealAfterScriptChange = await updateDeal(podcast.id, deal.id, dealBefore.version, {
      script_text: 'Read v2',
    });

    const episodeAfterScriptChange = await getEpisode(podcast.id, episode.id);
    const resvNeedsReview = findReservation(episodeAfterScriptChange, reservation.id);
    expect(resvNeedsReview?.status).toBe(RESERVATION_STATUS.NEEDS_REVIEW);

    const dealBeforeClose = await getDeal(podcast.id, deal.id);

    await updateDeal(podcast.id, deal.id, dealBeforeClose.version, {
      status: DEAL_STATUS.CLOSED,
    });

    const res = await getAs(`/podcasts/${podcast.id}/episodes/${episode.id}`);

    expectSuccess(res);
    const episodeData = res.body.data ?? res.body;

    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.CANCELED);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_committed_seconds).toBe(0);

    const dealData = await getDeal(podcast.id, deal.id);
    expect(dealData.budget_available_cents).toBe(5000);
  });

  test('DEEP_005: UNDER_REVIEW blocks publishing even after submit', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();

    const claim = await createClaim(podcast.id, {
      episode_id: episode.id,
      kind: CLAIM_KIND.RIGHTS,
    });

    const episodeWithClaim = await getEpisode(podcast.id, episode.id);
    expect(episodeWithClaim.clearance).toBe(CLEARANCE.UNDER_REVIEW);

    const submittedEpisode = await submitEpisode(podcast.id, episode.id, episodeWithClaim.version);

    const res = await postAction(
      `/podcasts/${podcast.id}/episodes/${episode.id}/publish`,
      submittedEpisode.version
    );

    expectErrorCode(res, ERROR_CODES.ERR_EPISODE_UNDER_REVIEW);

    const episodeData = await getEpisode(podcast.id, episode.id);
    expect(episodeData.status).toBe(EPISODE_STATUS.SUBMITTED);
    expect(episodeData.clearance).toBe(CLEARANCE.UNDER_REVIEW);
  });

  test('DEEP_006: Publishing succeeds after claim is rejected', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();

    const claim = await createClaim(podcast.id, {
      episode_id: episode.id,
      kind: CLAIM_KIND.RIGHTS,
    });

    const episodeWithClaim = await getEpisode(podcast.id, episode.id);
    expect(episodeWithClaim.clearance).toBe(CLEARANCE.UNDER_REVIEW);

    await closeClaim(podcast.id, claim.id, claim.version, 'REJECTED');

    const episodeAfterReject = await getEpisode(podcast.id, episode.id);
    expect(episodeAfterReject.clearance).toBe(CLEARANCE.CLEAR);

    const submittedEpisode = await submitEpisode(podcast.id, episode.id, episodeAfterReject.version);

    const res = await postAction(
      `/podcasts/${podcast.id}/episodes/${episode.id}/publish`,
      submittedEpisode.version
    );

    expectSuccess(res);

    const episodeData = await getEpisode(podcast.id, episode.id);
    expect(episodeData.status).toBe(EPISODE_STATUS.LIVE);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.posture).toBe(POSTURE.NORMAL);
  });

  test('DEEP_007: Closing one claim with WITHDRAWN keeps episode UNDER_REVIEW if another claim is open', async () => {

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
    expect(podcastBefore.posture).toBe(POSTURE.RESTRICTED);
    expect(podcastBefore.open_claim_count).toBe(2);

    const res = await postWithVersion(
      `/podcasts/${podcast.id}/claims/${claim2.id}/close`,
      { outcome: CLAIM_OUTCOME.WITHDRAWN },
      claim2.version
    );

    expectSuccess(res);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.posture).toBe(POSTURE.NORMAL);
    expect(podcastData.open_claim_count).toBe(1);

    const episodeData = await getEpisode(podcast.id, episode.id);
    expect(episodeData.clearance).toBe(CLEARANCE.UNDER_REVIEW);
  });

  test('DEEP_008: Episode retraction credits settled reservation and reverses budget', async () => {

    const { podcast, episode, deal } = await createFixtureStackLiveStd();

    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });

    const approvedResv = await approveReservation(podcast.id, reservation.id, reservation.version);

    const settledResv = await settleReservation(podcast.id, reservation.id, approvedResv.version);

    const dealAfterSettle = await getDeal(podcast.id, deal.id);
    expect(dealAfterSettle.budget_spent_cents).toBe(1000);

    const podcastAfterSettle = await getPodcast(podcast.id);
    expect(podcastAfterSettle.ad_committed_seconds).toBe(30);

    const episodeBeforeRetract = await getEpisode(podcast.id, episode.id);

    const res = await postAction(
      `/podcasts/${podcast.id}/episodes/${episode.id}/retract`,
      episodeBeforeRetract.version
    );

    expectSuccess(res);

    const episodeData = await getEpisode(podcast.id, episode.id);
    expect(episodeData.status).toBe(EPISODE_STATUS.RETRACTED);

    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.CREDITED);

    const dealData = await getDeal(podcast.id, deal.id);
    expect(dealData.budget_spent_cents).toBe(0);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_committed_seconds).toBe(0);
  });

  test('DEEP_009: Script change causes NEEDS_REVIEW and ops run does not clear it', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();

    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });

    await approveReservation(podcast.id, reservation.id, reservation.version);

    const dealBefore = await getDeal(podcast.id, deal.id);

    const podcastBefore = await getPodcast(podcast.id);
    expect(podcastBefore.ad_committed_seconds).toBe(30);
    const opsRunIndexBefore = podcastBefore.ops_run_index;

    const updateRes = await putWithVersion(
      `/podcasts/${podcast.id}/deals/${deal.id}`,
      { script_text: 'Read v2' },
      dealBefore.version
    );
    expectSuccess(updateRes);

    const episodeAfterScript = await getEpisode(podcast.id, episode.id);
    const resvAfterScript = findReservation(episodeAfterScript, reservation.id);
    expect(resvAfterScript?.status).toBe(RESERVATION_STATUS.NEEDS_REVIEW);

    const podcastForOps = await getPodcast(podcast.id);
    const opsRes = await postWithVersion(
      `/podcasts/${podcast.id}/run_ops`,
      {},
      podcastForOps.version!
    );

    expectSuccess(opsRes);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ops_run_index).toBe(opsRunIndexBefore + 1);
    expect(podcastData.ad_committed_seconds).toBe(30);

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.NEEDS_REVIEW);
  });

  test('DEEP_010: Reservation creation on RETRACTED episode after accepted claim', async () => {

    const { podcast, episode, deal, reservation, claim } = await createFixtureAcceptedClaimAuditPending();

    const podcastBefore = await getPodcast(podcast.id);
    expect(podcastBefore.posture).toBe(POSTURE.RESTRICTED);

    const episodeBefore = await getEpisode(podcast.id, episode.id);
    expect(episodeBefore.status).toBe(EPISODE_STATUS.RETRACTED);

    const res = await postAs(`/podcasts/${podcast.id}/reservations`, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });

    const podcastData = await getPodcast(podcast.id);

    if (res.status >= 200 && res.status < 300) {

      const resBody = res.body.data ?? res.body;
      expect(resBody.status).toBe(RESERVATION_STATUS.HOLD);
      expect(podcastData.ad_held_seconds).toBe(30);
    } else {

      expect(res.status).toBeGreaterThanOrEqual(400);
      expect(res.status).toBeLessThan(500);
      expect(podcastData.ad_held_seconds).toBe(0);
      expect(podcastData.ad_committed_seconds).toBe(0);
    }
  });

});
