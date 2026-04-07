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
  expectErrorCodeOneOf,
} from '../../../test-helpers/assertions';
import {
  createFixtureStackGeneralStd,
  createFixtureApprovedPre30,
  createFixtureAcceptedClaimAuditPending,
  createEpisode,
  createReservation,
  createClaim,
  getPodcast,
  getEpisode,
  getDeal,
  approveReservation,
  findReservation,
  submitEpisode,
  publishEpisode,
} from '../../../test-helpers/resources';
import {
  PLACEMENT,
  CONTENT_RATING,
  RESERVATION_STATUS,
  EPISODE_STATUS,
  POSTURE,
  ERROR_CODES,
  CLAIM_KIND,
  CLAIM_OUTCOME,
} from '../../../test-helpers/constants';

describe('Feature 9: Concurrency and Deterministic Ordering Tests', () => {

  test('CONCUR_001: Tightening episode capacity overbooks later-approved reservation and keeps earlier-approved', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();

    const r1 = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });
    const r1Approved = await approveReservation(podcast.id, r1.id, r1.version);

    const r2 = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.MID_ROLL,
      slot_seconds: 30,
    });
    const r2Approved = await approveReservation(podcast.id, r2.id, r2.version);

    const episodeV1 = await getEpisode(podcast.id, episode.id);
    expect(episodeV1.ad_slots_committed_seconds).toBe(60);

    const res = await putWithVersion(
      `/podcasts/${podcast.id}/episodes/${episode.id}`,
      { ad_slots_total_seconds: 30 },
      episodeV1.version
    );

    expectSuccess(res);

    const episodeAfter = await getEpisode(podcast.id, episode.id);
    expect(episodeAfter.ad_slots_total_seconds).toBe(30);
    expect(episodeAfter.ad_slots_committed_seconds).toBe(30);

    const r1After = findReservation(episodeAfter, r1.id);
    expect(r1After?.status).toBe(RESERVATION_STATUS.APPROVED);

    const r2After = findReservation(episodeAfter, r2.id);
    expect(r2After?.status).toBe(RESERVATION_STATUS.OVERBOOKED);

    const podcastAfter = await getPodcast(podcast.id);
    expect(podcastAfter.ad_committed_seconds).toBe(30);
  });

  test('CONCUR_002: Double-approve same reservation fails on second attempt with ERR_INVALID_STATE', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });

    const res1 = await postAction(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/approve`,
      reservation.version
    );
    expectSuccess(res1);
    const approvedReservation = (res1.body.data ?? res1.body);
    expect(approvedReservation.status).toBe(RESERVATION_STATUS.APPROVED);

    const res2 = await postAction(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/approve`,
      approvedReservation.version
    );

    expectErrorCode(res2, ERROR_CODES.ERR_INVALID_STATE);

    const podcastAfter = await getPodcast(podcast.id);
    expect(podcastAfter.ad_committed_seconds).toBe(30);
  });

  test('CONCUR_003: Concurrent deal updates with same If-Match - one succeeds, one fails ERR_VERSION_CONFLICT', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const dealV2 = await getDeal(podcast.id, deal.id);

    const res1 = await putWithVersion(
      `/podcasts/${podcast.id}/deals/${deal.id}`,
      { script_text: 'v2' },
      dealV2.version
    );

    const res2 = await putWithVersion(
      `/podcasts/${podcast.id}/deals/${deal.id}`,
      { status: 'PAUSED' },
      dealV2.version
    );

    expectSuccess(res1);

    expectErrorCode(res2, ERROR_CODES.ERR_VERSION_CONFLICT);

    const dealFinal = await getDeal(podcast.id, deal.id);
    expect(dealFinal.script_text).toBe('v2');
    expect(dealFinal.status).toBe('ACTIVE');
    expect(dealFinal.version).toBe(dealV2.version + 1);
  });

  test('CONCUR_004: Concurrent claim closes - one succeeds, one fails ERR_INVALID_STATE or ERR_VERSION_CONFLICT', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const claim = await createClaim(podcast.id, {
      episode_id: episode.id,
      kind: CLAIM_KIND.RIGHTS,
    });

    const podcastBefore = await getPodcast(podcast.id);
    expect(podcastBefore.open_claim_count).toBe(1);

    const res1 = await postWithVersion(
      `/podcasts/${podcast.id}/claims/${claim.id}/close`,
      { outcome: CLAIM_OUTCOME.REJECTED },
      claim.version
    );

    const res2 = await postWithVersion(
      `/podcasts/${podcast.id}/claims/${claim.id}/close`,
      { outcome: CLAIM_OUTCOME.REJECTED },
      claim.version
    );

    expectSuccess(res1);

    expectErrorCodeOneOf(res2, [ERROR_CODES.ERR_INVALID_STATE, ERROR_CODES.ERR_VERSION_CONFLICT]);

    const podcastAfter = await getPodcast(podcast.id);
    expect(podcastAfter.open_claim_count).toBe(0);
  });

  test('CONCUR_005: Concurrent reservation creates respect capacity limit - no negative available', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();

    const episode2 = await createEpisode(podcast.id, {
      title: 'Ep2',
      content_rating: CONTENT_RATING.GENERAL,
      ad_slots_total_seconds: 120,
    });

    const r1 = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 60,
    });

    const r2 = await createReservation(podcast.id, {
      episode_id: episode2.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 60,
    });

    const podcastBefore = await getPodcast(podcast.id);
    expect(podcastBefore.ad_held_seconds).toBe(120);
    expect(podcastBefore.ad_available_seconds).toBe(60);

    const [result3, result4] = await Promise.allSettled([
      postAs(`/podcasts/${podcast.id}/reservations`, {
        episode_id: episode2.id,
        deal_id: deal.id,
        placement: PLACEMENT.MID_ROLL,
        slot_seconds: 60,
      }),
      postAs(`/podcasts/${podcast.id}/reservations`, {
        episode_id: episode.id,
        deal_id: deal.id,
        placement: PLACEMENT.MID_ROLL,
        slot_seconds: 60,
      }),
    ]);

    expect(result3.status).toBe('fulfilled');
    expect(result4.status).toBe('fulfilled');

    const res3 = (result3 as PromiseFulfilledResult<any>).value;
    const res4 = (result4 as PromiseFulfilledResult<any>).value;

    const successes = [res3, res4].filter(r => r.status >= 200 && r.status < 300);
    const failures = [res3, res4].filter(r => r.status >= 400 && r.status < 500);

    expect(successes.length).toBe(1);
    expect(failures.length).toBe(1);

    expectErrorCode(failures[0], ERROR_CODES.ERR_CAPACITY_EXCEEDED);

    const podcastAfter = await getPodcast(podcast.id);
    expect(podcastAfter.ad_held_seconds).toBe(180);
    expect(podcastAfter.ad_available_seconds).toBe(0);

    expect(podcastAfter.ad_available_seconds).toBeGreaterThanOrEqual(0);
  });

  test('CONCUR_006: Concurrent episode edits with same If-Match - one succeeds, one fails ERR_VERSION_CONFLICT', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();

    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 60,
    });
    const approvedReservation = await approveReservation(podcast.id, reservation.id, reservation.version);

    const episodeV1 = await getEpisode(podcast.id, episode.id);
    expect(episodeV1.ad_slots_committed_seconds).toBe(60);

    const res1 = await putWithVersion(
      `/podcasts/${podcast.id}/episodes/${episode.id}`,
      { ad_slots_total_seconds: 30 },
      episodeV1.version
    );

    const res2 = await putWithVersion(
      `/podcasts/${podcast.id}/episodes/${episode.id}`,
      { ad_slots_total_seconds: 20 },
      episodeV1.version
    );

    expectSuccess(res1);

    expectErrorCode(res2, ERROR_CODES.ERR_VERSION_CONFLICT);

    const episodeFinal = await getEpisode(podcast.id, episode.id);
    expect(episodeFinal.ad_slots_total_seconds).toBe(30);

    const resvFinal = findReservation(episodeFinal, reservation.id);
    expect(resvFinal?.status).toBe(RESERVATION_STATUS.OVERBOOKED);
  });

  test('CONCUR_007: Concurrent retracts - one succeeds, one fails ERR_INVALID_STATE or ERR_VERSION_CONFLICT', async () => {

    const { podcast, episode, deal, reservation } = await createFixtureApprovedPre30();

    const submitted = await submitEpisode(podcast.id, episode.id, episode.version);
    const published = await publishEpisode(podcast.id, submitted.id, submitted.version);
    expect(published.status).toBe(EPISODE_STATUS.LIVE);

    const podcastBefore = await getPodcast(podcast.id);
    expect(podcastBefore.ad_committed_seconds).toBe(30);

    const res1 = await postAction(
      `/podcasts/${podcast.id}/episodes/${episode.id}/retract`,
      published.version
    );

    const res2 = await postAction(
      `/podcasts/${podcast.id}/episodes/${episode.id}/retract`,
      published.version
    );

    expectSuccess(res1);

    expectErrorCodeOneOf(res2, [ERROR_CODES.ERR_INVALID_STATE, ERROR_CODES.ERR_VERSION_CONFLICT]);

    const episodeFinal = await getEpisode(podcast.id, episode.id);
    expect(episodeFinal.status).toBe(EPISODE_STATUS.RETRACTED);

    const resvFinal = findReservation(episodeFinal, reservation.id);
    expect(resvFinal?.status).toBe(RESERVATION_STATUS.CANCELED);

    const podcastAfter = await getPodcast(podcast.id);
    expect(podcastAfter.ad_committed_seconds).toBe(0);
  });

  test('CONCUR_009: Claim close ACCEPTED replay with stale version fails without double-credit', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const claim = await createClaim(podcast.id, {
      episode_id: episode.id,
      kind: CLAIM_KIND.RIGHTS,
    });

    const res1 = await postWithVersion(
      `/podcasts/${podcast.id}/claims/${claim.id}/close`,
      { outcome: CLAIM_OUTCOME.ACCEPTED },
      claim.version
    );

    expectSuccess(res1);

    const episodeAfter1 = await getEpisode(podcast.id, episode.id);
    expect(episodeAfter1.status).toBe(EPISODE_STATUS.RETRACTED);

    const podcastAfter1 = await getPodcast(podcast.id);
    const openClaimCountAfter1 = podcastAfter1.open_claim_count;
    const postureAfter1 = podcastAfter1.posture;

    const res2 = await postWithVersion(
      `/podcasts/${podcast.id}/claims/${claim.id}/close`,
      { outcome: CLAIM_OUTCOME.ACCEPTED },
      claim.version
    );

    expectErrorCodeOneOf(res2, [ERROR_CODES.ERR_VERSION_CONFLICT, ERROR_CODES.ERR_INVALID_STATE]);

    const podcastAfter2 = await getPodcast(podcast.id);
    expect(podcastAfter2.open_claim_count).toBe(openClaimCountAfter1);
    expect(podcastAfter2.posture).toBe(postureAfter1);
  });

  test('CONCUR_010: Ops run replay with stale version fails, posture stays NORMAL', async () => {

    const { podcast, episode, deal, reservation, claim } = await createFixtureAcceptedClaimAuditPending();

    const podcastBefore = await getPodcast(podcast.id);
    expect(podcastBefore.posture).toBe(POSTURE.RESTRICTED);
    const opsRunIndexBefore = podcastBefore.ops_run_index;

    const res1 = await postWithVersion(
      `/podcasts/${podcast.id}/run_ops`,
      {},
      podcastBefore.version!
    );

    expectSuccess(res1);

    const podcastAfter1 = await getPodcast(podcast.id);
    expect(podcastAfter1.posture).toBe(POSTURE.NORMAL);
    expect(podcastAfter1.ops_run_index).toBe(opsRunIndexBefore + 1);

    const res2 = await postWithVersion(
      `/podcasts/${podcast.id}/run_ops`,
      {},
      podcastBefore.version!
    );

    expectErrorCode(res2, ERROR_CODES.ERR_VERSION_CONFLICT);

    const podcastAfter2 = await getPodcast(podcast.id);
    expect(podcastAfter2.posture).toBe(POSTURE.NORMAL);
    expect(podcastAfter2.ops_run_index).toBe(opsRunIndexBefore + 1);
  });

});
