import {
  postAs,
  postWithVersion,
  putWithVersion,
  postActionNoVersion,
  getAs,
  putRaw,
} from '../../../test-helpers/api-client';
import {
  expectSuccess,
  expectErrorCode,
  expectReservationStatus,
  expectPodcastInventory,
  expectEpisodeDraft,
  expectEpisodeSubmitted,
  expectDealStatus,
  expectVersionIncremented,
  expectEpisodeUnderReview,
} from '../../../test-helpers/assertions';
import {
  createPodcast,
  getPodcast,
  getEpisode,
  getDeal,
  createFixtureStackGeneralStd,
  createFixtureApprovedPre30,
  createFixtureHoldPre30,
  findReservation,
  unwrap,
} from '../../../test-helpers/resources';
import {
  ERROR_CODES,
  PLACEMENT,
  RESERVATION_STATUS,
  DEAL_STATUS,
  CLAIM_KIND,
} from '../../../test-helpers/constants';

describe('Feature 1: API Mechanics and Error Precedence', () => {

  test('ERR_002: POST /reservations/:R/cancel without If-Match returns ERR_MISSING_IF_MATCH', async () => {

    const { podcast, episode, reservation } = await createFixtureApprovedPre30();

    const res = await postActionNoVersion(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/cancel`
    );

    expectErrorCode(res, ERROR_CODES.ERR_MISSING_IF_MATCH);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(updatedEpisode, reservation.id);
    expect(resv).toBeDefined();
    expectReservationStatus(resv, RESERVATION_STATUS.APPROVED);
  });

  test('ERR_003: POST /reservations/:R/cancel with stale If-Match returns ERR_VERSION_CONFLICT', async () => {

    const { podcast, episode, reservation } = await createFixtureApprovedPre30();

    const staleVersion = reservation.version + 1;

    const res = await postWithVersion(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/cancel`,
      {},
      staleVersion
    );

    expectErrorCode(res, ERROR_CODES.ERR_VERSION_CONFLICT);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(updatedEpisode, reservation.id);
    expect(resv).toBeDefined();
    expectReservationStatus(resv, RESERVATION_STATUS.APPROVED);
  });

  test('ERR_005: POST /reservations with duplicate key returns ERR_DUPLICATE_RESERVATION', async () => {

    const { podcast, episode, deal } = await createFixtureStackGeneralStd();

    const res1 = await postAs(`/podcasts/${podcast.id}/reservations`, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });
    expectSuccess(res1);

    const res2 = await postAs(`/podcasts/${podcast.id}/reservations`, {
      episode_id: episode.id,
      deal_id: deal.id,
      placement: PLACEMENT.PRE_ROLL,
      slot_seconds: 30,
    });

    expectErrorCode(res2, ERROR_CODES.ERR_DUPLICATE_RESERVATION);

    const updatedPodcast = await getPodcast(podcast.id);
    expectPodcastInventory(updatedPodcast, { ad_held_seconds: 30 });
  });

  test('ERR_007: POST /reservations/:R/cancel on CANCELED returns ERR_INVALID_STATE', async () => {

    const { podcast, episode, reservation } = await createFixtureApprovedPre30();

    const res1 = await postWithVersion(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/cancel`,
      {},
      reservation.version
    );
    expectSuccess(res1);
    const canceledReservation = unwrap(res1.body);

    const res2 = await postWithVersion(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/cancel`,
      {},
      canceledReservation.version
    );

    expectErrorCode(res2, ERROR_CODES.ERR_INVALID_STATE);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(updatedEpisode, reservation.id);
    expectReservationStatus(resv, RESERVATION_STATUS.CANCELED);

    const updatedPodcast = await getPodcast(podcast.id);
    expectPodcastInventory(updatedPodcast, {
      ad_committed_seconds: 0,
      ad_held_seconds: 0,
    });
  });

  test('ERR_009: GET /podcasts/does_not_exist returns ERR_NOT_FOUND', async () => {

    await createFixtureStackGeneralStd();

    const res = await getAs('/podcasts/does_not_exist');

    expectErrorCode(res, ERROR_CODES.ERR_NOT_FOUND);
  });

  test('ERR_010: GET /podcasts/:P/episodes/does_not_exist returns ERR_NOT_FOUND', async () => {

    const { podcast } = await createFixtureStackGeneralStd();

    const res = await getAs(`/podcasts/${podcast.id}/episodes/does_not_exist`);

    expectErrorCode(res, ERROR_CODES.ERR_NOT_FOUND);

    const updatedPodcast = await getPodcast(podcast.id);
    expect(updatedPodcast.posture).toBe('NORMAL');
  });

  test('ERR_011: GET episode from different podcast returns ERR_NOT_FOUND', async () => {

    const { podcast: podcast1, episode } = await createFixtureStackGeneralStd();
    const podcast2 = await createPodcast({ name: 'Other', ad_capacity_seconds: 180 });

    const res = await getAs(`/podcasts/${podcast2.id}/episodes/${episode.id}`);

    expectErrorCode(res, ERROR_CODES.ERR_NOT_FOUND);

    const originalEpisode = await getEpisode(podcast1.id, episode.id);
    expect(originalEpisode.id).toBe(episode.id);
  });

  test('ERR_012: PUT /deals/:D without If-Match returns ERR_MISSING_IF_MATCH', async () => {

    const { podcast, deal } = await createFixtureStackGeneralStd();
    const dealV2 = await getDeal(podcast.id, deal.id);
    const pausedDeal = await putWithVersion(
      `/podcasts/${podcast.id}/deals/${deal.id}`,
      { status: DEAL_STATUS.PAUSED },
      dealV2.version
    );
    expectSuccess(pausedDeal);

    const res = await putRaw(
      `/podcasts/${podcast.id}/deals/${deal.id}`,
      { status: DEAL_STATUS.ACTIVE }
    );

    expectErrorCode(res, ERROR_CODES.ERR_MISSING_IF_MATCH);

    const updatedDeal = await getDeal(podcast.id, deal.id);
    expectDealStatus(updatedDeal, DEAL_STATUS.PAUSED);
  });

  test('ERR_013: PUT /deals/:D with correct If-Match succeeds and increments version', async () => {

    const { podcast, deal } = await createFixtureStackGeneralStd();
    const dealV2 = await getDeal(podcast.id, deal.id);
    const originalVersion = dealV2.version;

    const res = await putWithVersion(
      `/podcasts/${podcast.id}/deals/${deal.id}`,
      { status: DEAL_STATUS.PAUSED },
      dealV2.version
    );

    expectSuccess(res);

    const updatedDeal = await getDeal(podcast.id, deal.id);
    expectDealStatus(updatedDeal, DEAL_STATUS.PAUSED);
    expectVersionIncremented(updatedDeal.version, originalVersion);
  });

  test('ERR_014: PUT /deals/:D with stale If-Match returns ERR_VERSION_CONFLICT', async () => {

    const { podcast, deal } = await createFixtureStackGeneralStd();
    const dealV2 = await getDeal(podcast.id, deal.id);
    const staleVersion = dealV2.version;

    const pausedDeal = await putWithVersion(
      `/podcasts/${podcast.id}/deals/${deal.id}`,
      { status: DEAL_STATUS.PAUSED },
      dealV2.version
    );
    expectSuccess(pausedDeal);

    const res = await putWithVersion(
      `/podcasts/${podcast.id}/deals/${deal.id}`,
      { status: DEAL_STATUS.CLOSED },
      staleVersion
    );

    expectErrorCode(res, ERROR_CODES.ERR_VERSION_CONFLICT);

    const updatedDeal = await getDeal(podcast.id, deal.id);
    expectDealStatus(updatedDeal, DEAL_STATUS.PAUSED);
  });

  test('ERR_016: POST /episodes/:E/publish without If-Match returns ERR_MISSING_IF_MATCH', async () => {

    const { podcast, episode } = await createFixtureStackGeneralStd();

    const res = await postActionNoVersion(
      `/podcasts/${podcast.id}/episodes/${episode.id}/publish`
    );

    expectErrorCode(res, ERROR_CODES.ERR_MISSING_IF_MATCH);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    expectEpisodeDraft(updatedEpisode);
  });

  test('ERR_017: POST /episodes/:E/publish on DRAFT returns ERR_INVALID_STATE', async () => {

    const { podcast, episode } = await createFixtureStackGeneralStd();
    const episodeV1 = await getEpisode(podcast.id, episode.id);

    const res = await postWithVersion(
      `/podcasts/${podcast.id}/episodes/${episode.id}/publish`,
      {},
      episodeV1.version
    );

    expectErrorCode(res, ERROR_CODES.ERR_INVALID_STATE);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    expectEpisodeDraft(updatedEpisode);
  });

  test('ERR_018: POST /episodes/:E/submit on SUBMITTED returns ERR_INVALID_STATE', async () => {

    const { podcast, episode } = await createFixtureStackGeneralStd();
    const episodeV1 = await getEpisode(podcast.id, episode.id);

    const res1 = await postWithVersion(
      `/podcasts/${podcast.id}/episodes/${episode.id}/submit`,
      {},
      episodeV1.version
    );
    expectSuccess(res1);
    const submittedEpisode = unwrap(res1.body);

    const res2 = await postWithVersion(
      `/podcasts/${podcast.id}/episodes/${episode.id}/submit`,
      {},
      submittedEpisode.version
    );

    expectErrorCode(res2, ERROR_CODES.ERR_INVALID_STATE);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    expectEpisodeSubmitted(updatedEpisode);
  });

  test('ERR_019: POST /reservations/:R/approve on APPROVED returns ERR_INVALID_STATE', async () => {

    const { podcast, episode, reservation } = await createFixtureApprovedPre30();

    const res = await postWithVersion(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/approve`,
      {},
      reservation.version
    );

    expectErrorCode(res, ERROR_CODES.ERR_INVALID_STATE);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(updatedEpisode, reservation.id);
    expectReservationStatus(resv, RESERVATION_STATUS.APPROVED);

    const updatedPodcast = await getPodcast(podcast.id);
    expectPodcastInventory(updatedPodcast, { ad_committed_seconds: 30 });
  });

  test('ERR_020: POST /reservations/:R/settle on non-LIVE episode returns ERR_INVALID_STATE', async () => {

    const { podcast, episode, reservation } = await createFixtureApprovedPre30();

    const res = await postWithVersion(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/settle`,
      {},
      reservation.version
    );

    expectErrorCode(res, ERROR_CODES.ERR_INVALID_STATE);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    const resv = findReservation(updatedEpisode, reservation.id);
    expectReservationStatus(resv, RESERVATION_STATUS.APPROVED);
  });

  test('ERR_022: POST /reservations/:R/approve shifts ad_held to ad_committed', async () => {

    const { podcast, episode, deal, reservation } = await createFixtureHoldPre30();

    const dealBeforeApproval = await getDeal(podcast.id, deal.id);
    const expectedScriptVersion = dealBeforeApproval.script_version;

    const res = await postWithVersion(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/approve`,
      {},
      reservation.version
    );

    expectSuccess(res);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    const approvedResv = findReservation(updatedEpisode, reservation.id);
    expect(approvedResv).toBeDefined();
    expectReservationStatus(approvedResv, RESERVATION_STATUS.APPROVED);

    expect(approvedResv!.script_version_pinned).toBe(expectedScriptVersion);

    expect(updatedEpisode.ad_slots_held_seconds).toBe(0);
    expect(updatedEpisode.ad_slots_committed_seconds).toBe(30);

    const updatedPodcast = await getPodcast(podcast.id);
    expectPodcastInventory(updatedPodcast, {
      ad_held_seconds: 0,
      ad_committed_seconds: 30,
      ad_available_seconds: 150,
    });

    const updatedDeal = await getDeal(podcast.id, deal.id);
    expect(updatedDeal.budget_held_cents).toBe(0);
    expect(updatedDeal.budget_committed_cents).toBe(1000);
  });

  test('ERR_023: POST /reservations/:R/approve with stale If-Match returns ERR_VERSION_CONFLICT', async () => {

    const { podcast, reservation } = await createFixtureHoldPre30();

    const staleVersion = reservation.version + 1;

    const res = await postWithVersion(
      `/podcasts/${podcast.id}/reservations/${reservation.id}/approve`,
      {},
      staleVersion
    );

    expectErrorCode(res, ERROR_CODES.ERR_VERSION_CONFLICT);

    const updatedPodcast = await getPodcast(podcast.id);
    expectPodcastInventory(updatedPodcast, {
      ad_held_seconds: 30,
      ad_committed_seconds: 0,
    });
  });

  test('ERR_025: PUT /deals/:D with script_text increments script_version', async () => {

    const { podcast, deal } = await createFixtureStackGeneralStd();
    const dealBefore = await getDeal(podcast.id, deal.id);
    const originalScriptVersion = dealBefore.script_version;

    const res = await putWithVersion(
      `/podcasts/${podcast.id}/deals/${deal.id}`,
      { script_text: 'Read v2' },
      dealBefore.version
    );

    expectSuccess(res);

    const updatedDeal = await getDeal(podcast.id, deal.id);
    expect(updatedDeal.script_version).toBe(originalScriptVersion + 1);
  });

  test('ERR_026: PUT /deals/:D with bogus If-Match returns ERR_VERSION_CONFLICT', async () => {

    const { podcast, deal } = await createFixtureStackGeneralStd();

    const res = await putWithVersion(
      `/podcasts/${podcast.id}/deals/${deal.id}`,
      { status: DEAL_STATUS.ACTIVE },
      999
    );

    expectErrorCode(res, ERROR_CODES.ERR_VERSION_CONFLICT);

    const updatedDeal = await getDeal(podcast.id, deal.id);
    expectDealStatus(updatedDeal, DEAL_STATUS.ACTIVE);
  });

  test('ERR_028: POST /claims with duplicate key returns ERR_DUPLICATE_CLAIM', async () => {

    const { podcast, episode } = await createFixtureStackGeneralStd();

    const res1 = await postAs(`/podcasts/${podcast.id}/claims`, {
      episode_id: episode.id,
      kind: CLAIM_KIND.RIGHTS,
    });
    expectSuccess(res1);

    const res2 = await postAs(`/podcasts/${podcast.id}/claims`, {
      episode_id: episode.id,
      kind: CLAIM_KIND.RIGHTS,
    });

    expectErrorCode(res2, ERROR_CODES.ERR_DUPLICATE_CLAIM);

    const updatedPodcast = await getPodcast(podcast.id);
    expect(updatedPodcast.open_claim_count).toBe(1);

    const updatedEpisode = await getEpisode(podcast.id, episode.id);
    expectEpisodeUnderReview(updatedEpisode);
  });

});
