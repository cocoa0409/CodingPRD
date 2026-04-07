import {
  postAs,
  postWithVersion,
} from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
  expectPodcastInventory,
  expectOpsRunIndex,
  expectPostureNormal,
  expectPostureRestricted,
  expectOpenClaimCount,
  expectReservationStatus,
  expectDealBudget,
  expectEpisodeRetracted,
  expectReservationCredited,
} from '../../../test-helpers/assertions';
import {
  getPodcast,
  getEpisode,
  getDeal,
  createReservation,
  cancelReservation,
  createClaim,
  closeClaim,
  runOps,
  createFixtureStackGeneralStd,
  createFixtureHoldPre30,
  createFixtureAcceptedClaimAuditPending,
  createFixtureRestrictedTwoOpenClaims,
  findReservation,
} from '../../../test-helpers/resources';
import {
  PLACEMENT,
  RESERVATION_STATUS,
  CLAIM_KIND,
  ERROR_CODES,
} from '../../../test-helpers/constants';

describe('Feature 2: Podcast Ops Runs and Housekeeping', () => {

  test('OPS_001: First ops run increments index but reservation stays HOLD', async () => {

    const { podcast, episode, reservation } = await createFixtureHoldPre30();
    let podcastState = await getPodcast(podcast.id);
    expect(podcastState.ops_run_index).toBe(0);
    expect(podcastState.ad_held_seconds).toBe(30);

    await runOps(podcast.id, podcastState.version!);

    podcastState = await getPodcast(podcast.id);
    expectOpsRunIndex(podcastState, 1);
    expectPodcastInventory(podcastState, { ad_held_seconds: 30 });

    const episodeState = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(episodeState, reservation.id);
    expect(resv).toBeDefined();
    expectReservationStatus(resv, RESERVATION_STATUS.HOLD);
  });

  test('OPS_002: Second ops run expires HOLD reservation and releases inventory', async () => {

    const { podcast, episode, deal, reservation } = await createFixtureHoldPre30();
    let podcastState = await getPodcast(podcast.id);
    await runOps(podcast.id, podcastState.version!);
    podcastState = await getPodcast(podcast.id);
    expect(podcastState.ops_run_index).toBe(1);

    await runOps(podcast.id, podcastState.version!);

    podcastState = await getPodcast(podcast.id);
    expectOpsRunIndex(podcastState, 2);
    expectPodcastInventory(podcastState, { ad_held_seconds: 0 });

    const episodeState = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(episodeState, reservation.id);
    expect(resv).toBeDefined();
    expectReservationStatus(resv, RESERVATION_STATUS.EXPIRED);

    const dealState = await getDeal(podcast.id, deal.id);
    expectDealBudget(dealState, { budget_held_cents: 0 });
  });

  test('OPS_003: Ops run after expiry keeps reservation EXPIRED and totals at zero', async () => {

    const { podcast, episode, reservation } = await createFixtureHoldPre30();
    let podcastState = await getPodcast(podcast.id);
    await runOps(podcast.id, podcastState.version!);
    podcastState = await getPodcast(podcast.id);
    await runOps(podcast.id, podcastState.version!);
    let episodeState = await getEpisode(podcast.id, episode.id);
    let resv = findReservation(episodeState, reservation.id);
    expect(resv).toBeDefined();
    expectReservationStatus(resv, RESERVATION_STATUS.EXPIRED);

    podcastState = await getPodcast(podcast.id);
    await runOps(podcast.id, podcastState.version!);

    podcastState = await getPodcast(podcast.id);
    expectOpsRunIndex(podcastState, 3);
    expectPodcastInventory(podcastState, {
      ad_held_seconds: 0,
      ad_committed_seconds: 0,
    });

    episodeState = await getEpisode(podcast.id, episode.id);
    resv = findReservation(episodeState, reservation.id);
    expect(resv).toBeDefined();
    expectReservationStatus(resv, RESERVATION_STATUS.EXPIRED);
  });

  test('OPS_004: POST run_ops with stale If-Match returns ERR_VERSION_CONFLICT', async () => {

    const { podcast, episode, reservation } = await createFixtureHoldPre30();
    let podcastState = await getPodcast(podcast.id);
    const staleVersion = podcastState.version!;
    const res1 = await postWithVersion(`/podcasts/${podcast.id}/run_ops`, {}, staleVersion);
    expectSuccess(res1);

    const res2 = await postWithVersion(`/podcasts/${podcast.id}/run_ops`, {}, staleVersion);

    expectErrorCode(res2, ERROR_CODES.ERR_VERSION_CONFLICT);

    podcastState = await getPodcast(podcast.id);
    expectOpsRunIndex(podcastState, 1);

    const episodeState = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(episodeState, reservation.id);
    expect(resv).toBeDefined();
    expectReservationStatus(resv, RESERVATION_STATUS.HOLD);
  });

  test('OPS_006: Ops run clears posture to NORMAL after accepted claim audit with no open claims', async () => {

    const { podcast, episode, reservation } = await createFixtureAcceptedClaimAuditPending();
    let podcastState = await getPodcast(podcast.id);
    expectPostureRestricted(podcastState);
    expectOpenClaimCount(podcastState, 0);

    await runOps(podcast.id, podcastState.version!);

    podcastState = await getPodcast(podcast.id);
    expectPostureNormal(podcastState);

    const episodeState = await getEpisode(podcast.id, episode.id);
    expectEpisodeRetracted(episodeState);

    const resv = findReservation(episodeState, reservation.id);
    expect(resv).toBeDefined();
    expectReservationCredited(resv);
  });

  test('OPS_007: Ops run keeps RESTRICTED posture when open_claim_count >= 2', async () => {

    const { podcast } = await createFixtureRestrictedTwoOpenClaims();
    let podcastState = await getPodcast(podcast.id);
    expectOpenClaimCount(podcastState, 2);
    expectPostureRestricted(podcastState);

    await runOps(podcast.id, podcastState.version!);

    podcastState = await getPodcast(podcast.id);
    expectPostureRestricted(podcastState);
    expectOpenClaimCount(podcastState, 2);
  });

  test('OPS_008: Closing one claim when open_claim_count=2 sets posture to NORMAL', async () => {

    const { podcast, claim1 } = await createFixtureRestrictedTwoOpenClaims();
    let podcastState = await getPodcast(podcast.id);
    expectOpenClaimCount(podcastState, 2);
    expectPostureRestricted(podcastState);

    await closeClaim(podcast.id, claim1.id, claim1.version, 'REJECTED');

    podcastState = await getPodcast(podcast.id);
    expectOpenClaimCount(podcastState, 1);
    expectPostureNormal(podcastState);
  });

  test('OPS_009: Single ops run does not expire fresh HOLD reservation', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });
    let podcastState = await getPodcast(podcast.id);
    expect(podcastState.ad_held_seconds).toBe(30);

    await runOps(podcast.id, podcastState.version!);

    podcastState = await getPodcast(podcast.id);
    expectPodcastInventory(podcastState, { ad_held_seconds: 30 });
    expect(podcastState.ops_run_index).toBeGreaterThanOrEqual(1);

    const episodeState = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(episodeState, reservation.id);
    expect(resv).toBeDefined();
    expectReservationStatus(resv, RESERVATION_STATUS.HOLD);
  });

  test('OPS_010: Ops run with open_claim_count=1 keeps posture NORMAL', async () => {

    const { podcast, episode } = await createFixtureStackGeneralStd();
    await createClaim(podcast.id, {
      episode_id: episode.id,
      kind: CLAIM_KIND.RIGHTS,
    });
    let podcastState = await getPodcast(podcast.id);
    expectOpenClaimCount(podcastState, 1);

    await runOps(podcast.id, podcastState.version!);

    podcastState = await getPodcast(podcast.id);
    expectOpenClaimCount(podcastState, 1);
    expectPostureNormal(podcastState);
  });

  test('OPS_011: Creating reservation after two ops runs starts in HOLD', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    let podcastState = await getPodcast(podcast.id);
    await runOps(podcast.id, podcastState.version!);
    podcastState = await getPodcast(podcast.id);
    await runOps(podcast.id, podcastState.version!);
    podcastState = await getPodcast(podcast.id);
    expect(podcastState.ops_run_index).toBe(2);

    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });

    expectReservationStatus(reservation, RESERVATION_STATUS.HOLD);
    podcastState = await getPodcast(podcast.id);
    expectPodcastInventory(podcastState, { ad_held_seconds: 30 });
    expectOpsRunIndex(podcastState, 2);
  });

  test('OPS_012: Ops run does not change CANCELED reservation to EXPIRED', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });
    await cancelReservation(podcast.id, reservation.id, reservation.version);

    let podcastState = await getPodcast(podcast.id);
    await runOps(podcast.id, podcastState.version!);

    podcastState = await getPodcast(podcast.id);
    expectPodcastInventory(podcastState, { ad_held_seconds: 0 });

    const episodeState = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(episodeState, reservation.id);
    expect(resv).toBeDefined();
    expectReservationStatus(resv, RESERVATION_STATUS.CANCELED);
  });

  test('OPS_013: Ops run keeps RESTRICTED when new claim opened after accepted claim audit', async () => {

    const { podcast, episode } = await createFixtureAcceptedClaimAuditPending();
    await createClaim(podcast.id, {
      episode_id: episode.id,
      kind: CLAIM_KIND.BRAND_SAFETY,
    });

    let podcastState = await getPodcast(podcast.id);
    await runOps(podcast.id, podcastState.version!);

    podcastState = await getPodcast(podcast.id);
    expectPostureRestricted(podcastState);
    expectOpenClaimCount(podcastState, 1);
  });

  test('OPS_014: Sequential ops runs increment ops_run_index from 1 to 2', async () => {

    const { podcast } = await createFixtureStackGeneralStd();
    let podcastState = await getPodcast(podcast.id);
    await runOps(podcast.id, podcastState.version!);
    podcastState = await getPodcast(podcast.id);
    expectOpsRunIndex(podcastState, 1);

    await runOps(podcast.id, podcastState.version!);

    podcastState = await getPodcast(podcast.id);
    expectOpsRunIndex(podcastState, 2);
  });

  test('OPS_015: Ops run without housekeeping keeps derived fields stable', async () => {

    const { podcast } = await createFixtureStackGeneralStd();
    let podcastState = await getPodcast(podcast.id);
    expect(podcastState.ad_available_seconds).toBe(180);

    await runOps(podcast.id, podcastState.version!);

    podcastState = await getPodcast(podcast.id);
    expect(podcastState.ad_available_seconds).toBe(180);
    expectPostureNormal(podcastState);
  });

  test('OPS_016: Hold expiry after two ops runs releases deal budget', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });
    let podcastState = await getPodcast(podcast.id);
    await runOps(podcast.id, podcastState.version!);
    podcastState = await getPodcast(podcast.id);
    await runOps(podcast.id, podcastState.version!);

    const dealState = await getDeal(podcast.id, deal.id);

    expectDealBudget(dealState, {
      budget_held_cents: 0,
      budget_available_cents: 5000,
    });

    const episodeState = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(episodeState, reservation.id);
    expect(resv).toBeDefined();
    expectReservationStatus(resv, RESERVATION_STATUS.EXPIRED);
  });

  test('OPS_017: New reservation after two ops runs is HOLD and needs two more ops to expire', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    let podcastState = await getPodcast(podcast.id);
    await runOps(podcast.id, podcastState.version!);
    podcastState = await getPodcast(podcast.id);
    await runOps(podcast.id, podcastState.version!);
    podcastState = await getPodcast(podcast.id);

    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });

    expectReservationStatus(reservation, RESERVATION_STATUS.HOLD);

    podcastState = await getPodcast(podcast.id);
    expectOpsRunIndex(podcastState, 2);
    expectPodcastInventory(podcastState, { ad_held_seconds: 30 });

    await runOps(podcast.id, podcastState.version!);
    podcastState = await getPodcast(podcast.id);
    expectOpsRunIndex(podcastState, 3);
    let episodeState = await getEpisode(podcast.id, episode.id);
    let resv = findReservation(episodeState, reservation.id);
    expect(resv).toBeDefined();
    expectReservationStatus(resv, RESERVATION_STATUS.HOLD);
    expectPodcastInventory(podcastState, { ad_held_seconds: 30 });

    await runOps(podcast.id, podcastState.version!);
    podcastState = await getPodcast(podcast.id);
    expectOpsRunIndex(podcastState, 4);
    episodeState = await getEpisode(podcast.id, episode.id);
    resv = findReservation(episodeState, reservation.id);
    expect(resv).toBeDefined();
    expectReservationStatus(resv, RESERVATION_STATUS.EXPIRED);
    expectPodcastInventory(podcastState, { ad_held_seconds: 0 });

    const dealState = await getDeal(podcast.id, deal.id);
    expectDealBudget(dealState, {
      budget_held_cents: 0,
      budget_available_cents: 5000,
    });
  });

  test('OPS_018: POST run_ops with stale If-Match on clean podcast returns ERR_VERSION_CONFLICT', async () => {

    const { podcast } = await createFixtureStackGeneralStd();
    let podcastState = await getPodcast(podcast.id);
    const staleVersion = podcastState.version!;
    const res1 = await postWithVersion(`/podcasts/${podcast.id}/run_ops`, {}, staleVersion);
    expectSuccess(res1);

    const res2 = await postWithVersion(`/podcasts/${podcast.id}/run_ops`, {}, staleVersion);

    expectErrorCode(res2, ERROR_CODES.ERR_VERSION_CONFLICT);

    podcastState = await getPodcast(podcast.id);
    expectOpsRunIndex(podcastState, 1);
  });

  test('OPS_019: Closing claim as WITHDRAWN reduces open_claim_count and sets posture NORMAL', async () => {

    const { podcast, claim2 } = await createFixtureRestrictedTwoOpenClaims();

    await closeClaim(podcast.id, claim2.id, claim2.version, 'WITHDRAWN');

    const podcastState = await getPodcast(podcast.id);
    expectOpenClaimCount(podcastState, 1);
    expectPostureNormal(podcastState);
  });

  test('OPS_020: Ops run clears posture to NORMAL after accepted claim when all claims closed', async () => {

    const { podcast, episode } = await createFixtureStackGeneralStd();
    const claim = await createClaim(podcast.id, {
      episode_id: episode.id,
      kind: CLAIM_KIND.RIGHTS,
    });
    await closeClaim(podcast.id, claim.id, claim.version, 'ACCEPTED');

    let podcastState = await getPodcast(podcast.id);
    expectPostureRestricted(podcastState);
    expectOpenClaimCount(podcastState, 0);

    await runOps(podcast.id, podcastState.version!);

    podcastState = await getPodcast(podcast.id);
    expectPostureNormal(podcastState);
  });

});
