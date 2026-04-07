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
  expectCapacityExceeded,
  expectPodcastInventory,
  expectDealBudget,
  expectReservationStatus,
  expectReservationHold,
  expectReservationApproved,
  expectReservationCanceled,
  expectReservationSettled,
  expectReservationCredited,
  expectReservationExpired,
  expectReservationOverbooked,
  expectReservationNeedsReview,
  expectScriptVersionPinned,
  expectReservationInEpisode,
  expectEpisodeStatus,
  expectEpisodeUnderReview,
  expectEpisodeClear,
  expectEpisodeInventory,
} from '../../../test-helpers/assertions';
import {
  createFixtureStackGeneralStd,
  createFixtureStackGeneralFamily,
  createFixtureStackMatureFamily,
  createFixtureStackLiveStd,
  createFixtureStackTightCapacity,
  createFixtureHoldPre30,
  createFixtureApprovedPre30,
  createFixtureSettledPre30,
  createPodcast,
  createEpisode,
  createDeal,
  createReservation,
  createClaim,
  getPodcast,
  getEpisode,
  getDeal,
  updateEpisode,
  updateDeal,
  activateDeal,
  approveReservation,
  cancelReservation,
  settleReservation,
  submitEpisode,
  publishEpisode,
  retractEpisode,
  runOps,
  findReservation,
} from '../../../test-helpers/resources';
import {
  PLACEMENT,
  CONTENT_RATING,
  BRAND_TIER,
  RESERVATION_STATUS,
  EPISODE_STATUS,
  CLEARANCE,
  ERROR_CODES,
  CAPACITY_SCOPE,
} from '../../../test-helpers/constants';

describe('Feature 5: Reservation Lifecycle and Constraints', () => {

  test('RESV_001: Creating reservation creates HOLD and consumes inventory/budget', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();

    const res = await postAs(`/podcasts/${podcast.id}/reservations`, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });

    expectSuccess(res);
    const reservation = res.body.data ?? res.body;

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_held_seconds).toBe(30);
    expect(podcastData.ad_available_seconds).toBe(150);

    const dealData = await getDeal(podcast.id, deal.id);
    expect(dealData.budget_held_cents).toBe(1000);
    expect(dealData.budget_available_cents).toBe(4000);

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.HOLD);
  });

  test('RESV_002: Approving reservation shifts held to committed and pins script_version', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });

    const dealBefore = await getDeal(podcast.id, deal.id);
    const expectedScriptVersion = dealBefore.script_version;

    const res = await postAction(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/approve`,
      reservation.version
    );

    expectSuccess(res);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_held_seconds).toBe(0);
    expect(podcastData.ad_committed_seconds).toBe(30);

    const dealData = await getDeal(podcast.id, deal.id);
    expect(dealData.budget_held_cents).toBe(0);
    expect(dealData.budget_committed_cents).toBe(1000);

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.APPROVED);
    expect(resv?.script_version_pinned).toBe(expectedScriptVersion);
  });

  test('RESV_003: Canceling APPROVED reservation releases commitments', async () => {

    const { podcast, episode, deal, reservation } = await createFixtureApprovedPre30();

    const dealBefore = await getDeal(podcast.id, deal.id);
    expect(dealBefore.budget_committed_cents).toBe(1000);
    const podcastBefore = await getPodcast(podcast.id);
    expect(podcastBefore.ad_committed_seconds).toBe(30);

    const res = await postAction(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/cancel`,
      reservation.version
    );

    expectSuccess(res);

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.CANCELED);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_committed_seconds).toBe(0);
    expect(podcastData.ad_available_seconds).toBe(180);

    const dealData = await getDeal(podcast.id, deal.id);
    expect(dealData.budget_committed_cents).toBe(0);
    expect(dealData.budget_available_cents).toBe(5000);
  });

  test('RESV_004: Canceling HOLD reservation releases holds', async () => {

    const { podcast, episode, deal, reservation } = await createFixtureHoldPre30();

    const podcastBefore = await getPodcast(podcast.id);
    expect(podcastBefore.ad_held_seconds).toBe(30);

    const res = await postAction(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/cancel`,
      reservation.version
    );

    expectSuccess(res);

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.CANCELED);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_held_seconds).toBe(0);

    const dealData = await getDeal(podcast.id, deal.id);
    expect(dealData.budget_held_cents).toBe(0);
  });

  test('RESV_005: Creating reservation consuming all capacity sets ad_available_seconds to 0', async () => {

    const { podcast, episode, deal } = await createFixtureStackTightCapacity();

    const res = await postAs(`/podcasts/${podcast.id}/reservations`, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 60,
    });

    expectSuccess(res);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_held_seconds).toBe(60);
    expect(podcastData.ad_available_seconds).toBe(0);

    const episodeData = await getEpisode(podcast.id, episode.id);
    expect(episodeData.ad_slots_held_seconds).toBe(60);
  });

  test('RESV_006: Creating reservation exceeding podcast capacity fails with ERR_CAPACITY_EXCEEDED', async () => {

    const { podcast, episode, deal } = await createFixtureStackTightCapacity();
    await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 60,
    });

    const res = await postAs(`/podcasts/${podcast.id}/reservations`, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.MID_ROLL,
      slot_seconds: 30,
    });

    expectErrorCode(res, ERROR_CODES.ERR_CAPACITY_EXCEEDED);
    const body = res.body.data ?? res.body;
    expect([CAPACITY_SCOPE.PODCAST, CAPACITY_SCOPE.EPISODE]).toContain(body.capacity_scope);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_held_seconds).toBe(60);
    expect(podcastData.ad_available_seconds).toBe(0);
  });

  test('RESV_007: Creating reservation exceeding episode capacity fails with ERR_CAPACITY_EXCEEDED EPISODE', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 60,
    });

    const res = await postAs(`/podcasts/${podcast.id}/reservations`, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.MID_ROLL,
      slot_seconds: 30,
    });

    expectCapacityExceeded(res, CAPACITY_SCOPE.EPISODE);

    const episodeData = await getEpisode(podcast.id, episode.id);
    expect(episodeData.ad_slots_held_seconds).toBe(60);
  });

  test('RESV_008: Creating second reservation for same deal/placement has consistent state', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const r1 = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });

    const res = await postAs(`/podcasts/${podcast.id}/reservations`, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });

    const episodeData = await getEpisode(podcast.id, episode.id);
    const preRollReservations = episodeData.reservations?.filter(
      (r: any) => r.deal_id === deal.id && r.placement === PLACEMENT.PRE_ROLL
    );

    if (res.status >= 200 && res.status < 300) {

      expect(preRollReservations?.length).toBe(2);
      const podcastData = await getPodcast(podcast.id);
      expect(podcastData.ad_held_seconds).toBe(60);
    } else {

      expectErrorCode(res, ERROR_CODES.ERR_DUPLICATE_RESERVATION);
      expect(preRollReservations?.length).toBe(1);
    }
  });

  test('RESV_009: Creating reservation for same placement after CANCELED has consistent state', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const r1 = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });
    await cancelReservation(podcast.id, r1.id, r1.version);

    const res = await postAs(`/podcasts/${podcast.id}/reservations`, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resv1 = findReservation(episodeData, r1.id);
    expect(resv1?.status).toBe(RESERVATION_STATUS.CANCELED);

    if (res.status >= 200 && res.status < 300) {

      const r2 = res.body.data ?? res.body;
      const resv2 = findReservation(episodeData, r2.id);
      expect(resv2?.status).toBe(RESERVATION_STATUS.HOLD);
    } else {

      expectErrorCode(res, ERROR_CODES.ERR_DUPLICATE_RESERVATION);
    }
  });

  test('RESV_010: Creating duplicate reservation with APPROVED previous has consistent state', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const r1 = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });
    await approveReservation(podcast.id, r1.id, r1.version);

    const res = await postAs(`/podcasts/${podcast.id}/reservations`, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resv1 = findReservation(episodeData, r1.id);
    expect(resv1?.status).toBe(RESERVATION_STATUS.APPROVED);

    if (res.status >= 200 && res.status < 300) {

      const r2 = res.body.data ?? res.body;
      const resv2 = findReservation(episodeData, r2.id);
      expect(resv2?.status).toBe(RESERVATION_STATUS.HOLD);
    } else {

      expectErrorCode(res, ERROR_CODES.ERR_DUPLICATE_RESERVATION);
    }
  });

  test('RESV_011: Approving reservation on UNDER_REVIEW episode fails with ERR_EPISODE_UNDER_REVIEW', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    await createClaim(podcast.id, {
      episode_id: episode.id,
      kind: 'RIGHTS',
    });
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

    expectErrorCode(res, ERROR_CODES.ERR_EPISODE_UNDER_REVIEW);

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.HOLD);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_held_seconds).toBe(30);
  });

  test('RESV_012: Creating HOLD reservation on UNDER_REVIEW episode succeeds', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    await createClaim(podcast.id, {
      episode_id: episode.id,
      kind: 'RIGHTS',
    });

    const res = await postAs(`/podcasts/${podcast.id}/reservations`, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });

    expectSuccess(res);
    const reservation = res.body.data ?? res.body;
    expect(reservation.status).toBe(RESERVATION_STATUS.HOLD);

    const episodeData = await getEpisode(podcast.id, episode.id);
    expect(episodeData.clearance).toBe(CLEARANCE.UNDER_REVIEW);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_held_seconds).toBe(30);
  });

  test('RESV_013: Approving FAMILY_SAFE deal on MATURE episode fails with ERR_BRAND_SAFETY_MISMATCH', async () => {

    const { podcast, episode, deal } = await createFixtureStackMatureFamily();
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

    expectErrorCode(res, ERROR_CODES.ERR_BRAND_SAFETY_MISMATCH);

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.HOLD);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_held_seconds).toBe(30);
  });

  test('RESV_014: Approving FAMILY_SAFE deal on GENERAL episode succeeds', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralFamily();
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

    const dealData = await getDeal(podcast.id, deal.id);
    expect(dealData.budget_committed_cents).toBe(1000);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_committed_seconds).toBe(30);
  });

  test('RESV_015: Podcast capacity is global across episodes', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const ep2 = await createEpisode(podcast.id, {
      title: 'Ep2',
      content_rating: CONTENT_RATING.GENERAL,
      ad_slots_total_seconds: 120,
    });
    const ep3 = await createEpisode(podcast.id, {
      title: 'Ep3',
      content_rating: CONTENT_RATING.GENERAL,
      ad_slots_total_seconds: 60,
    });

    await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 60,
    });

    await createReservation(podcast.id, {
      episode_id: ep2.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 60,
    });
    await createReservation(podcast.id, {
      episode_id: ep2.id,
      deal_id: deal.id,
      placement: PLACEMENT.MID_ROLL,
      slot_seconds: 60,
    });

    const podcastBefore = await getPodcast(podcast.id);
    expect(podcastBefore.ad_held_seconds).toBe(180);

    const res = await postAs(`/podcasts/${podcast.id}/reservations`, {
      episode_id: ep3.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });

    expectCapacityExceeded(res, CAPACITY_SCOPE.PODCAST);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_held_seconds).toBe(180);
  });

  test('RESV_016: Canceling HOLD reservation releases budget_available_cents', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });

    const res = await postAction(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/cancel`,
      reservation.version
    );

    expectSuccess(res);

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.CANCELED);

    const dealData = await getDeal(podcast.id, deal.id);
    expect(dealData.budget_available_cents).toBe(5000);
  });

  test('RESV_017: Canceling already CANCELED reservation fails with ERR_INVALID_STATE', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });
    const canceled = await cancelReservation(podcast.id, reservation.id, reservation.version);

    const res = await postAction(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/cancel`,
      canceled.version
    );

    expectErrorCode(res, ERROR_CODES.ERR_INVALID_STATE);

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.CANCELED);
  });

  test('RESV_018: Settling APPROVED reservation on LIVE episode succeeds', async () => {

    const { podcast, episode, deal } = await createFixtureStackLiveStd();
    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });
    const approved = await approveReservation(podcast.id, reservation.id, reservation.version);

    const res = await postAction(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/settle`,
      approved.version
    );

    expectSuccess(res);

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.SETTLED);

    const dealData = await getDeal(podcast.id, deal.id);
    expect(dealData.budget_spent_cents).toBe(1000);
    expect(dealData.budget_committed_cents).toBe(0);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_committed_seconds).toBe(30);
  });

  test('RESV_019: Canceling SETTLED reservation fails with ERR_INVALID_STATE', async () => {

    const { podcast, episode, deal, reservation } = await createFixtureSettledPre30();

    const res = await postAction(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/cancel`,
      reservation.version
    );

    expectErrorCode(res, ERROR_CODES.ERR_INVALID_STATE);

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.SETTLED);

    const dealData = await getDeal(podcast.id, deal.id);
    expect(dealData.budget_spent_cents).toBe(1000);
  });

  test('RESV_020: Retracting episode with SETTLED reservation credits it', async () => {

    const { podcast, episode, deal, reservation } = await createFixtureSettledPre30();

    const dealBefore = await getDeal(podcast.id, deal.id);
    expect(dealBefore.budget_spent_cents).toBe(1000);

    const episodeData = await getEpisode(podcast.id, episode.id);

    const res = await postAction(
      `/podcasts/${podcast.id}/episodes/${episode.id}/retract`,
      episodeData.version
    );

    expectSuccess(res);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(updatedEpisode, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.CREDITED);

    const dealData = await getDeal(podcast.id, deal.id);
    expect(dealData.budget_spent_cents).toBe(0);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_committed_seconds).toBe(0);
  });

  test('RESV_021: Settling NEEDS_REVIEW reservation fails with ERR_INVALID_STATE', async () => {

    const { podcast, episode, deal, reservation } = await createFixtureApprovedPre30();
    const dealV2 = await getDeal(podcast.id, deal.id);
    await updateDeal(podcast.id, deal.id, dealV2.version, { script_text: 'Read v2' });

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resvData = findReservation(episodeData, reservation.id);
    expect(resvData?.status).toBe(RESERVATION_STATUS.NEEDS_REVIEW);

    const res = await postAction(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/settle`,
      resvData!.version
    );

    expectErrorCode(res, ERROR_CODES.ERR_INVALID_STATE);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(updatedEpisode, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.NEEDS_REVIEW);

    const dealData = await getDeal(podcast.id, deal.id);
    expect(dealData.budget_spent_cents).toBe(0);
  });

  test('RESV_022: Settling HOLD reservation fails with ERR_INVALID_STATE', async () => {

    const { podcast, episode, deal } = await createFixtureStackLiveStd();
    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.MID_ROLL,
      slot_seconds: 30,
    });

    const res = await postAction(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/settle`,
      reservation.version
    );

    expectErrorCode(res, ERROR_CODES.ERR_INVALID_STATE);

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.HOLD);
  });

  test('RESV_023: Settling reservation on UNDER_REVIEW episode fails with ERR_EPISODE_UNDER_REVIEW', async () => {

    const { podcast, episode, deal } = await createFixtureStackLiveStd();
    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.MID_ROLL,
      slot_seconds: 30,
    });
    const approved = await approveReservation(podcast.id, reservation.id, reservation.version);
    await createClaim(podcast.id, {
      episode_id: episode.id,
      kind: 'RIGHTS',
    });

    const res = await postAction(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/settle`,
      approved.version
    );

    expectErrorCode(res, ERROR_CODES.ERR_EPISODE_UNDER_REVIEW);

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.APPROVED);
  });

  test('RESV_024: Multiple reservations across episodes count against podcast capacity', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const ep2 = await createEpisode(podcast.id, {
      title: 'Ep2',
      content_rating: CONTENT_RATING.GENERAL,
      ad_slots_total_seconds: 60,
    });
    const ep3 = await createEpisode(podcast.id, {
      title: 'Ep3',
      content_rating: CONTENT_RATING.GENERAL,
      ad_slots_total_seconds: 120,
    });
    await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 60,
    });
    await createReservation(podcast.id, {
      episode_id: ep2.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 60,
    });

    const podcastBefore = await getPodcast(podcast.id);
    expect(podcastBefore.ad_held_seconds).toBe(120);

    const res = await postAs(`/podcasts/${podcast.id}/reservations`, {
      episode_id: ep3.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 70,
    });

    expectCapacityExceeded(res, CAPACITY_SCOPE.PODCAST);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_held_seconds).toBe(120);
  });

  test('RESV_025: Approval shifts held to committed and updates ad_available_seconds', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });

    const podcastBefore = await getPodcast(podcast.id);
    expect(podcastBefore.ad_held_seconds).toBe(30);

    await approveReservation(podcast.id, reservation.id, reservation.version);

    const res = await getAs(`/podcasts/${podcast.id}`);

    expectSuccess(res);
    const podcastData = res.body.data ?? res.body;
    expect(podcastData.ad_held_seconds).toBe(0);
    expect(podcastData.ad_committed_seconds).toBe(30);
    expect(podcastData.ad_available_seconds).toBe(150);
  });

  test('RESV_026: Re-approving NEEDS_REVIEW reservation pins to current script_version', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.MID_ROLL,
      slot_seconds: 30,
    });
    await approveReservation(podcast.id, reservation.id, reservation.version);

    const dealV2 = await getDeal(podcast.id, deal.id);
    await updateDeal(podcast.id, deal.id, dealV2.version, { script_text: 'Read v2' });

    const dealAfterUpdate = await getDeal(podcast.id, deal.id);
    const expectedScriptVersion = dealAfterUpdate.script_version;

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resvData = findReservation(episodeData, reservation.id);
    expect(resvData?.status).toBe(RESERVATION_STATUS.NEEDS_REVIEW);

    const res = await postAction(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/approve`,
      resvData!.version
    );

    expectSuccess(res);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(updatedEpisode, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.APPROVED);
    expect(resv?.script_version_pinned).toBe(expectedScriptVersion);
  });

  test('RESV_027: Re-approving OVERBOOKED reservation when capacity still 0 fails with ERR_CAPACITY_EXCEEDED', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.MID_ROLL,
      slot_seconds: 30,
    });
    await approveReservation(podcast.id, reservation.id, reservation.version);

    const episodeV1 = await getEpisode(podcast.id, episode.id);
    await updateEpisode(podcast.id, episode.id, episodeV1.version, { ad_slots_total_seconds: 0 });

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resvData = findReservation(episodeData, reservation.id);
    expect(resvData?.status).toBe(RESERVATION_STATUS.OVERBOOKED);

    const res = await postAction(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/approve`,
      resvData!.version
    );

    expectCapacityExceeded(res, CAPACITY_SCOPE.EPISODE);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(updatedEpisode, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.OVERBOOKED);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_committed_seconds).toBe(0);
  });

  test('RESV_028: OVERBOOKED reservation remains OVERBOOKED after capacity increase until re-approved', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.MID_ROLL,
      slot_seconds: 30,
    });
    await approveReservation(podcast.id, reservation.id, reservation.version);

    const episodeV1 = await getEpisode(podcast.id, episode.id);
    await updateEpisode(podcast.id, episode.id, episodeV1.version, { ad_slots_total_seconds: 0 });

    const episodeV2 = await getEpisode(podcast.id, episode.id);

    const res = await putWithVersion(
      `/podcasts/${podcast.id}/episodes/${episode.id}`,
      { ad_slots_total_seconds: 60 },
      episodeV2.version
    );

    expectSuccess(res);

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.OVERBOOKED);
    expect(episodeData.ad_slots_committed_seconds).toBe(0);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_committed_seconds).toBe(0);
  });

  test('RESV_029: Re-approving OVERBOOKED reservation after capacity restored succeeds', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.MID_ROLL,
      slot_seconds: 30,
    });
    await approveReservation(podcast.id, reservation.id, reservation.version);

    const episodeV1 = await getEpisode(podcast.id, episode.id);
    await updateEpisode(podcast.id, episode.id, episodeV1.version, { ad_slots_total_seconds: 0 });

    const episodeV2 = await getEpisode(podcast.id, episode.id);
    await updateEpisode(podcast.id, episode.id, episodeV2.version, { ad_slots_total_seconds: 60 });

    const episodeV3 = await getEpisode(podcast.id, episode.id);
    const resvData = findReservation(episodeV3, reservation.id);
    expect(resvData?.status).toBe(RESERVATION_STATUS.OVERBOOKED);

    const res = await postAction(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/approve`,
      resvData!.version
    );

    expectSuccess(res);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(updatedEpisode, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.APPROVED);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_committed_seconds).toBe(30);

    const dealData = await getDeal(podcast.id, deal.id);
    expect(dealData.budget_committed_cents).toBe(1000);
  });

  test('RESV_030: Podcast capacity tracks holds and commitments globally', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const ep2 = await createEpisode(podcast.id, {
      title: 'Ep2',
      content_rating: CONTENT_RATING.GENERAL,
      ad_slots_total_seconds: 60,
    });
    const r1 = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 60,
    });
    await approveReservation(podcast.id, r1.id, r1.version);

    const res = await postAs(`/podcasts/${podcast.id}/reservations`, {
      episode_id: ep2.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 60,
    });

    expectSuccess(res);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_held_seconds).toBe(60);
    expect(podcastData.ad_committed_seconds).toBe(60);
    expect(podcastData.ad_available_seconds).toBe(60);
  });

  test('RESV_031: Approving second reservation shifts held to committed correctly', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const ep2 = await createEpisode(podcast.id, {
      title: 'Ep2',
      content_rating: CONTENT_RATING.GENERAL,
      ad_slots_total_seconds: 60,
    });
    const r1 = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 60,
    });
    await approveReservation(podcast.id, r1.id, r1.version);
    const r2 = await createReservation(podcast.id, {
      episode_id: ep2.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 60,
    });

    const res = await postAction(
      `/podcasts/${podcast.id}/reservations/${r2.id}/approve`,
      r2.version
    );

    expectSuccess(res);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_committed_seconds).toBe(120);
    expect(podcastData.ad_available_seconds).toBe(60);
  });

  test('RESV_032: Multiple holds count against podcast capacity', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const ep2 = await createEpisode(podcast.id, {
      title: 'Ep2',
      content_rating: CONTENT_RATING.GENERAL,
      ad_slots_total_seconds: 60,
    });
    const ep3 = await createEpisode(podcast.id, {
      title: 'Ep3',
      content_rating: CONTENT_RATING.GENERAL,
      ad_slots_total_seconds: 60,
    });
    const ep4 = await createEpisode(podcast.id, {
      title: 'Ep4',
      content_rating: CONTENT_RATING.GENERAL,
      ad_slots_total_seconds: 60,
    });
    await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 60,
    });
    await createReservation(podcast.id, {
      episode_id: ep2.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 60,
    });
    await createReservation(podcast.id, {
      episode_id: ep3.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 60,
    });

    const podcastBefore = await getPodcast(podcast.id);
    expect(podcastBefore.ad_held_seconds).toBe(180);

    const res = await postAs(`/podcasts/${podcast.id}/reservations`, {
      episode_id: ep4.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 10,
    });

    expectCapacityExceeded(res, CAPACITY_SCOPE.PODCAST);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_held_seconds).toBe(180);
  });

  test('RESV_033: Creating HOLD reservation on LIVE episode has consistent state', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const episodeV1 = await getEpisode(podcast.id, episode.id);
    const submitted = await submitEpisode(podcast.id, episode.id, episodeV1.version);
    await publishEpisode(podcast.id, episode.id, submitted.version);

    const res = await postAs(`/podcasts/${podcast.id}/reservations`, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });

    const episodeData = await getEpisode(podcast.id, episode.id);
    expect(episodeData.status).toBe(EPISODE_STATUS.LIVE);

    if (res.status >= 200 && res.status < 300) {

      const reservation = res.body.data ?? res.body;
      expect(reservation.status).toBe(RESERVATION_STATUS.HOLD);
      expect(episodeData.ad_slots_held_seconds).toBe(30);
    } else {

      expect(episodeData.ad_slots_held_seconds ?? 0).toBe(0);
    }
  });

  test('RESV_034: Settling after script update (NEEDS_REVIEW) fails with ERR_INVALID_STATE', async () => {

    const { podcast, episode, deal } = await createFixtureStackLiveStd();
    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });
    const approved = await approveReservation(podcast.id, reservation.id, reservation.version);

    const dealV2 = await getDeal(podcast.id, deal.id);
    await updateDeal(podcast.id, deal.id, dealV2.version, { script_text: 'Read v2' });

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resvData = findReservation(episodeData, reservation.id);
    expect(resvData?.status).toBe(RESERVATION_STATUS.NEEDS_REVIEW);

    const res = await postAction(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/settle`,
      resvData!.version
    );

    expectErrorCode(res, ERROR_CODES.ERR_INVALID_STATE);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(updatedEpisode, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.NEEDS_REVIEW);
  });

  test('RESV_035: Settlement succeeds after re-approving NEEDS_REVIEW', async () => {

    const { podcast, episode, deal } = await createFixtureStackLiveStd();
    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });
    const approved = await approveReservation(podcast.id, reservation.id, reservation.version);

    const dealV2 = await getDeal(podcast.id, deal.id);
    await updateDeal(podcast.id, deal.id, dealV2.version, { script_text: 'Read v2' });

    const dealAfterUpdate = await getDeal(podcast.id, deal.id);
    const expectedScriptVersion = dealAfterUpdate.script_version;

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resvData = findReservation(episodeData, reservation.id);
    await approveReservation(podcast.id, reservation.id, resvData!.version);

    const episodeV2 = await getEpisode(podcast.id, episode.id);
    const resvV2 = findReservation(episodeV2, reservation.id);
    expect(resvV2?.status).toBe(RESERVATION_STATUS.APPROVED);

    const res = await postAction(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/settle`,
      resvV2!.version
    );

    expectSuccess(res);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(updatedEpisode, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.SETTLED);
    expect(resv?.script_version_pinned).toBe(expectedScriptVersion);

    const dealData = await getDeal(podcast.id, deal.id);
    expect(dealData.budget_spent_cents).toBe(1000);
  });

  test('RESV_036: Canceling APPROVED reservation releases commitments', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.POST_ROLL,
      slot_seconds: 30,
    });
    const approved = await approveReservation(podcast.id, reservation.id, reservation.version);

    const podcastBefore = await getPodcast(podcast.id);
    expect(podcastBefore.ad_committed_seconds).toBe(30);

    const res = await postAction(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/cancel`,
      approved.version
    );

    expectSuccess(res);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_committed_seconds).toBe(0);

    const dealData = await getDeal(podcast.id, deal.id);
    expect(dealData.budget_committed_cents).toBe(0);
  });

  test('RESV_037: Approving CANCELED reservation fails with ERR_INVALID_STATE', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.POST_ROLL,
      slot_seconds: 30,
    });
    const canceled = await cancelReservation(podcast.id, reservation.id, reservation.version);

    const res = await postAction(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/approve`,
      canceled.version
    );

    expectErrorCode(res, ERROR_CODES.ERR_INVALID_STATE);

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.CANCELED);
  });

  test('RESV_038: Approving EXPIRED reservation fails with ERR_INVALID_STATE', async () => {

    const { podcast, episode, deal, reservation } = await createFixtureHoldPre30();

    let podcastData = await getPodcast(podcast.id);
    await runOps(podcast.id, podcastData.version!);
    podcastData = await getPodcast(podcast.id);
    await runOps(podcast.id, podcastData.version!);

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resvData = findReservation(episodeData, reservation.id);
    expect(resvData?.status).toBe(RESERVATION_STATUS.EXPIRED);

    const res = await postAction(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/approve`,
      resvData!.version
    );

    expectErrorCode(res, ERROR_CODES.ERR_INVALID_STATE);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(updatedEpisode, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.EXPIRED);
  });

  test('RESV_039: Episode with OVERBOOKED reservation can still be submitted', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });
    await approveReservation(podcast.id, reservation.id, reservation.version);

    const episodeV1 = await getEpisode(podcast.id, episode.id);
    await updateEpisode(podcast.id, episode.id, episodeV1.version, { ad_slots_total_seconds: 0 });

    const episodeV2 = await getEpisode(podcast.id, episode.id);
    const resvData = findReservation(episodeV2, reservation.id);
    expect(resvData?.status).toBe(RESERVATION_STATUS.OVERBOOKED);

    const res = await postAction(
      `/podcasts/${podcast.id}/episodes/${episode.id}/submit`,
      episodeV2.version
    );

    expectSuccess(res);

    const episodeData = await getEpisode(podcast.id, episode.id);
    expect(episodeData.status).toBe(EPISODE_STATUS.SUBMITTED);
  });

  test('RESV_040: Publishing episode with OVERBOOKED reservation is blocked', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });
    await approveReservation(podcast.id, reservation.id, reservation.version);

    const episodeV1 = await getEpisode(podcast.id, episode.id);
    await updateEpisode(podcast.id, episode.id, episodeV1.version, { ad_slots_total_seconds: 0 });

    const episodeV2 = await getEpisode(podcast.id, episode.id);
    const submitted = await submitEpisode(podcast.id, episode.id, episodeV2.version);

    const res = await postAction(
      `/podcasts/${podcast.id}/episodes/${episode.id}/publish`,
      submitted.version
    );

    expect(res.status).toBeGreaterThanOrEqual(400);

    const episodeData = await getEpisode(podcast.id, episode.id);
    expect(episodeData.status).toBe(EPISODE_STATUS.SUBMITTED);
  });

  test('RESV_041: Canceling OVERBOOKED reservation releases nothing (it was not consuming)', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });
    await approveReservation(podcast.id, reservation.id, reservation.version);

    const episodeV1 = await getEpisode(podcast.id, episode.id);
    await updateEpisode(podcast.id, episode.id, episodeV1.version, { ad_slots_total_seconds: 0 });

    const episodeV2 = await getEpisode(podcast.id, episode.id);
    const resvData = findReservation(episodeV2, reservation.id);
    expect(resvData?.status).toBe(RESERVATION_STATUS.OVERBOOKED);

    await cancelReservation(podcast.id, reservation.id, resvData!.version);

    const res = await getAs(`/podcasts/${podcast.id}/episodes/${episode.id}`);

    expectSuccess(res);

    const episodeData = res.body.data ?? res.body;
    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.CANCELED);

    const overbookedReservations = episodeData.reservations?.filter(
      (r: any) => r.status === RESERVATION_STATUS.OVERBOOKED
    );
    expect(overbookedReservations?.length ?? 0).toBe(0);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_available_seconds).toBe(180);
  });

  test('RESV_042: Settlement requires episode LIVE and moves committed to spent', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });
    await approveReservation(podcast.id, reservation.id, reservation.version);

    const episodeV1 = await getEpisode(podcast.id, episode.id);
    const submitted = await submitEpisode(podcast.id, episode.id, episodeV1.version);
    await publishEpisode(podcast.id, episode.id, submitted.version);

    const episodeV2 = await getEpisode(podcast.id, episode.id);
    const resvData = findReservation(episodeV2, reservation.id);

    const res = await postAction(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/settle`,
      resvData!.version
    );

    expectSuccess(res);

    const episodeData = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(episodeData, reservation.id);
    expect(resv?.status).toBe(RESERVATION_STATUS.SETTLED);

    const dealData = await getDeal(podcast.id, deal.id);
    expect(dealData.budget_spent_cents).toBe(1000);
  });

  test('RESV_043: Canceling one of multiple HOLD reservations releases only that reservation\'s holds', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const ep2 = await createEpisode(podcast.id, {
      title: 'Ep2',
      content_rating: CONTENT_RATING.GENERAL,
      ad_slots_total_seconds: 60,
    });
    const r1 = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 60,
    });
    const r2 = await createReservation(podcast.id, {
      episode_id: ep2.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 60,
    });

    const podcastBefore = await getPodcast(podcast.id);
    expect(podcastBefore.ad_held_seconds).toBe(120);
    const dealBefore = await getDeal(podcast.id, deal.id);
    expect(dealBefore.budget_held_cents).toBe(2000);

    const res = await postAction(
      `/podcasts/${podcast.id}/reservations/${r2.id}/cancel`,
      r2.version
    );

    expectSuccess(res);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_held_seconds).toBe(60);

    const dealData = await getDeal(podcast.id, deal.id);
    expect(dealData.budget_held_cents).toBe(1000);
  });

  test('RESV_044: Creating reservation after APPROVED then CANCELED has consistent state', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const reservation = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });
    const approved = await approveReservation(podcast.id, reservation.id, reservation.version);
    await cancelReservation(podcast.id, reservation.id, approved.version);

    const res = await postAs(`/podcasts/${podcast.id}/reservations`, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });

    const episodeData = await getEpisode(podcast.id, episode.id);
    const oldResv = findReservation(episodeData, reservation.id);
    expect(oldResv?.status).toBe(RESERVATION_STATUS.CANCELED);

    if (res.status >= 200 && res.status < 300) {

      const newResv = res.body.data ?? res.body;
      expect(newResv.status).toBe(RESERVATION_STATUS.HOLD);
    } else {

      expectErrorCode(res, ERROR_CODES.ERR_DUPLICATE_RESERVATION);
    }
  });

  test('RESV_045: Podcast capacity at limit blocks even 1s additional reservation', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();
    const ep2 = await createEpisode(podcast.id, {
      title: 'Ep2',
      content_rating: CONTENT_RATING.GENERAL,
      ad_slots_total_seconds: 60,
    });
    const ep3 = await createEpisode(podcast.id, {
      title: 'Ep3',
      content_rating: CONTENT_RATING.GENERAL,
      ad_slots_total_seconds: 60,
    });
    const ep4 = await createEpisode(podcast.id, {
      title: 'Ep4',
      content_rating: CONTENT_RATING.GENERAL,
      ad_slots_total_seconds: 60,
    });

    const r1 = await createReservation(podcast.id, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 60,
    });
    await approveReservation(podcast.id, r1.id, r1.version);

    const r2 = await createReservation(podcast.id, {
      episode_id: ep2.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 60,
    });
    await approveReservation(podcast.id, r2.id, r2.version);

    const r3 = await createReservation(podcast.id, {
      episode_id: ep3.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 60,
    });
    await approveReservation(podcast.id, r3.id, r3.version);

    const podcastBefore = await getPodcast(podcast.id);
    expect(podcastBefore.ad_committed_seconds).toBe(180);
    expect(podcastBefore.ad_available_seconds).toBe(0);

    const res = await postAs(`/podcasts/${podcast.id}/reservations`, {
      episode_id: ep4.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 1,
    });

    expectCapacityExceeded(res, CAPACITY_SCOPE.PODCAST);

    const podcastData = await getPodcast(podcast.id);
    expect(podcastData.ad_committed_seconds).toBe(180);
    expect(podcastData.ad_available_seconds).toBe(0);
  });

});
